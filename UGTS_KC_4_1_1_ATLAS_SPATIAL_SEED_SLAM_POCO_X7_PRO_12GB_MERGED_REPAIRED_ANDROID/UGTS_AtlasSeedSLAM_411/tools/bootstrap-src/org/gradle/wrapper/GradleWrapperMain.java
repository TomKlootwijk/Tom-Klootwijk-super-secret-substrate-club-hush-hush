package org.gradle.wrapper;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.net.URLConnection;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.CodeSource;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.List;
import java.util.Locale;
import java.util.Properties;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Source-auditable UGTS verified Gradle bootstrap.
 *
 * This is intentionally small and transparent. It reads the standard wrapper
 * properties file, downloads the declared distribution, verifies its required
 * SHA-256 before extraction, and executes the distribution's Gradle launcher.
 * It is not represented as the upstream Gradle wrapper JAR.
 */
public final class GradleWrapperMain {
    private static final String SELF_TEST = "--bootstrap-self-test";
    private static final int MAX_REDIRECTS = 8;
    private static final long MAX_UNCOMPRESSED_BYTES = 2_000_000_000L;

    private GradleWrapperMain() {}

    public static void main(String[] args) throws Exception {
        File jar = ownJar();
        File propertiesFile = new File(jar.getParentFile(), "gradle-wrapper.properties");
        Properties properties = load(propertiesFile);
        String distributionUrl = required(properties, "distributionUrl");
        String expectedSha256 = required(properties, "distributionSha256Sum")
                .toLowerCase(Locale.ROOT);
        int timeout = parseInt(properties.getProperty("networkTimeout"), 30_000);
        validateSha256(expectedSha256);

        if (args.length == 1 && SELF_TEST.equals(args[0])) {
            System.out.println("UGTS verified Gradle bootstrap: PASS");
            System.out.println("properties=" + propertiesFile.getCanonicalPath());
            System.out.println("distributionUrl=" + distributionUrl);
            System.out.println("distributionSha256Sum=" + expectedSha256);
            return;
        }

        File gradleHome = gradleUserHome();
        String fileName = new File(new URI(distributionUrl).getPath()).getName();
        String versionTag = fileName.replaceAll("[^A-Za-z0-9._-]", "_");
        File installBase = new File(
                gradleHome,
                "wrapper/dists/ugts-verified/" + versionTag + "/" + expectedSha256.substring(0, 16));
        if (!installBase.exists() && !installBase.mkdirs()) {
            throw new IOException("Cannot create " + installBase);
        }
        File lockFile = new File(installBase, ".install.lock");
        File distributionRoot;
        try (RandomAccessFile lockAccess = new RandomAccessFile(lockFile, "rw");
                FileChannel channel = lockAccess.getChannel();
                FileLock ignored = channel.lock()) {
            distributionRoot = findDistributionRoot(installBase);
            if (distributionRoot == null) {
                File zip = new File(installBase, fileName);
                ensureDistribution(distributionUrl, expectedSha256, timeout, zip);
                File temporary = new File(installBase, ".extracting");
                deleteTree(temporary.toPath());
                if (!temporary.mkdirs()) {
                    throw new IOException("Cannot create extraction directory " + temporary);
                }
                extractSafely(zip, temporary);
                File extractedRoot = findDistributionRoot(temporary);
                if (extractedRoot == null) {
                    throw new IOException("Downloaded archive contains no Gradle launcher");
                }
                File finalRoot = new File(installBase, extractedRoot.getName());
                deleteTree(finalRoot.toPath());
                try {
                    Files.move(
                            extractedRoot.toPath(),
                            finalRoot.toPath(),
                            StandardCopyOption.ATOMIC_MOVE);
                } catch (IOException atomicFailure) {
                    Files.move(
                            extractedRoot.toPath(),
                            finalRoot.toPath(),
                            StandardCopyOption.REPLACE_EXISTING);
                }
                deleteTree(temporary.toPath());
                distributionRoot = finalRoot;
            }
        }

        int exit = execute(distributionRoot, args);
        if (exit != 0) {
            System.exit(exit);
        }
    }

    private static File ownJar() throws Exception {
        CodeSource source = GradleWrapperMain.class.getProtectionDomain().getCodeSource();
        if (source == null) {
            throw new IllegalStateException("Cannot locate bootstrap JAR");
        }
        return new File(source.getLocation().toURI()).getCanonicalFile();
    }

    private static Properties load(File file) throws IOException {
        Properties properties = new Properties();
        try (InputStream input = new FileInputStream(file)) {
            properties.load(input);
        }
        return properties;
    }

    private static String required(Properties properties, String key) {
        String value = properties.getProperty(key);
        if (value == null || value.trim().isEmpty()) {
            throw new IllegalArgumentException("Missing " + key);
        }
        return value.trim();
    }

    private static int parseInt(String value, int fallback) {
        if (value == null) {
            return fallback;
        }
        try {
            return Math.max(1_000, Integer.parseInt(value));
        } catch (NumberFormatException ignored) {
            return fallback;
        }
    }

    private static void validateSha256(String value) {
        if (!value.matches("[0-9a-f]{64}")) {
            throw new IllegalArgumentException("distributionSha256Sum must be 64 lowercase hex digits");
        }
    }

    private static File gradleUserHome() {
        String explicit = System.getenv("GRADLE_USER_HOME");
        if (explicit != null && !explicit.trim().isEmpty()) {
            return new File(explicit);
        }
        return new File(System.getProperty("user.home"), ".gradle");
    }

    private static void ensureDistribution(
            String url, String expectedSha256, int timeout, File destination) throws Exception {
        if (destination.isFile() && expectedSha256.equals(sha256(destination))) {
            return;
        }
        File temporary = new File(destination.getParentFile(), destination.getName() + ".part");
        if (temporary.exists() && !temporary.delete()) {
            throw new IOException("Cannot replace " + temporary);
        }
        download(new URL(url), temporary, timeout, 0);
        String actual = sha256(temporary);
        if (!expectedSha256.equals(actual)) {
            temporary.delete();
            throw new SecurityException(
                    "Gradle distribution SHA-256 mismatch: expected "
                            + expectedSha256 + ", got " + actual);
        }
        Files.move(
                temporary.toPath(),
                destination.toPath(),
                StandardCopyOption.REPLACE_EXISTING);
    }

    private static void download(URL url, File destination, int timeout, int redirects)
            throws Exception {
        if (redirects > MAX_REDIRECTS) {
            throw new IOException("Too many redirects while downloading " + url);
        }
        URLConnection connection = url.openConnection();
        connection.setConnectTimeout(timeout);
        connection.setReadTimeout(timeout);
        connection.setRequestProperty("User-Agent", "UGTS-Gradle-Bootstrap/4.1.1");
        if (connection instanceof HttpURLConnection) {
            HttpURLConnection http = (HttpURLConnection) connection;
            http.setInstanceFollowRedirects(false);
            int code = http.getResponseCode();
            if (code == 301 || code == 302 || code == 303 || code == 307 || code == 308) {
                String location = http.getHeaderField("Location");
                http.disconnect();
                if (location == null) {
                    throw new IOException("Redirect without Location header");
                }
                download(new URL(url, location), destination, timeout, redirects + 1);
                return;
            }
            if (code < 200 || code >= 300) {
                throw new IOException("HTTP " + code + " downloading " + url);
            }
        }
        try (InputStream input = new BufferedInputStream(connection.getInputStream());
                OutputStream output = new BufferedOutputStream(new FileOutputStream(destination))) {
            byte[] buffer = new byte[128 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0) {
                output.write(buffer, 0, count);
            }
        }
    }

    private static String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new BufferedInputStream(new FileInputStream(file))) {
            byte[] buffer = new byte[128 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0) {
                digest.update(buffer, 0, count);
            }
        }
        StringBuilder hex = new StringBuilder(64);
        for (byte value : digest.digest()) {
            hex.append(String.format(Locale.ROOT, "%02x", value & 255));
        }
        return hex.toString();
    }

    private static void extractSafely(File archive, File destination) throws Exception {
        String root = destination.getCanonicalPath() + File.separator;
        long total = 0L;
        try (ZipFile zip = new ZipFile(archive)) {
            Enumeration<? extends ZipEntry> entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                File output = new File(destination, entry.getName());
                String canonical = output.getCanonicalPath();
                if (!canonical.startsWith(root)) {
                    throw new SecurityException("Unsafe ZIP path " + entry.getName());
                }
                if (entry.isDirectory()) {
                    if (!output.exists() && !output.mkdirs()) {
                        throw new IOException("Cannot create " + output);
                    }
                    continue;
                }
                long declared = entry.getSize();
                if (declared > 0) {
                    total += declared;
                    if (total > MAX_UNCOMPRESSED_BYTES) {
                        throw new SecurityException("Archive exceeds extraction budget");
                    }
                }
                File parent = output.getParentFile();
                if (!parent.exists() && !parent.mkdirs()) {
                    throw new IOException("Cannot create " + parent);
                }
                try (InputStream input = new BufferedInputStream(zip.getInputStream(entry));
                        OutputStream target =
                                new BufferedOutputStream(new FileOutputStream(output))) {
                    byte[] buffer = new byte[128 * 1024];
                    int count;
                    while ((count = input.read(buffer)) >= 0) {
                        target.write(buffer, 0, count);
                    }
                }
            }
        }
    }

    private static File findDistributionRoot(File base) {
        if (!base.isDirectory()) {
            return null;
        }
        File direct = launcher(base);
        if (direct != null) {
            return base;
        }
        File[] children = base.listFiles(File::isDirectory);
        if (children == null) {
            return null;
        }
        for (File child : children) {
            if (".extracting".equals(child.getName())) {
                continue;
            }
            if (launcher(child) != null) {
                return child;
            }
        }
        return null;
    }

    private static File launcher(File root) {
        File unix = new File(root, "bin/gradle");
        File windows = new File(root, "bin/gradle.bat");
        if (unix.isFile() || windows.isFile()) {
            return isWindows() ? windows : unix;
        }
        return null;
    }

    private static int execute(File root, String[] args) throws Exception {
        File launcher = launcher(root);
        if (launcher == null) {
            throw new IOException("Gradle launcher is missing from " + root);
        }
        if (!isWindows()) {
            launcher.setExecutable(true, true);
        }
        List<String> command = new ArrayList<>();
        if (isWindows()) {
            command.add("cmd.exe");
            command.add("/d");
            command.add("/c");
        }
        command.add(launcher.getAbsolutePath());
        for (String arg : args) {
            command.add(arg);
        }
        ProcessBuilder builder = new ProcessBuilder(command);
        builder.directory(new File(System.getProperty("user.dir")));
        builder.inheritIO();
        Process process = builder.start();
        return process.waitFor();
    }

    private static boolean isWindows() {
        return System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("win");
    }

    private static void deleteTree(Path path) throws IOException {
        if (!Files.exists(path)) {
            return;
        }
        try (java.util.stream.Stream<Path> stream = Files.walk(path)) {
            Path[] paths = stream.sorted((a, b) -> b.compareTo(a)).toArray(Path[]::new);
            for (Path value : paths) {
                Files.deleteIfExists(value);
            }
        }
    }
}
