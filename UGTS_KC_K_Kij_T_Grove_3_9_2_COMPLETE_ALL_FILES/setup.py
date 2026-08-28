from setuptools import find_packages, setup

setup(
    name="ugts-kc-signature",
    version="3.9.2",
    package_dir={"": "src"},
    packages=find_packages("src"),
    package_data={"ugts_kc3.android_template": ["project/**/*"], "": ["py.typed"]},
    include_package_data=True,
    description="UGTS-KC 3.9.2 K-Kij-T Grove vector, 3D and native Android game runtime",
    python_requires=">=3.10",
    entry_points={"console_scripts": ["ugts-kc=ugts_kc3.cli:main"]},
)
