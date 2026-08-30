param(
    [Parameter(Mandatory=$true)][string]$InputSpv,
    [Parameter(Mandatory=$true)][string]$OutputHeader
)

$bytes = [System.IO.File]::ReadAllBytes($InputSpv)
if (($bytes.Length % 4) -ne 0) { throw "SPIR-V byte count is not uint32 aligned" }
$words = [System.Collections.Generic.List[string]]::new()
for ($offset = 0; $offset -lt $bytes.Length; $offset += 4) {
    $word = [System.BitConverter]::ToUInt32($bytes, $offset)
    $words.Add(('0x{0:x8}u' -f $word))
}
$lines = [System.Collections.Generic.List[string]]::new()
for ($offset = 0; $offset -lt $words.Count; $offset += 8) {
    $count = [System.Math]::Min(8, $words.Count - $offset)
    $lines.Add('    ' + (($words.GetRange($offset, $count)) -join ',') + ',')
}
$body = @(
    '#pragma once'
    ''
    '#include <array>'
    '#include <cstdint>'
    ''
    'namespace kc {'
    ''
    '// Generated from chrono_gsp4_full_substrate.comp with NDK r29 glslc:'
    '// glslc --target-env=vulkan1.1 -O ... -o chrono_gsp4_full_substrate.spv'
    "inline constexpr std::array<std::uint32_t,$($words.Count)> ChronoGsp4FullSubstrateSpirv{{"
) + $lines + @(
    '}};'
    ''
    '} // namespace kc'
    ''
)
[System.IO.File]::WriteAllLines($OutputHeader, $body, [System.Text.UTF8Encoding]::new($false))
