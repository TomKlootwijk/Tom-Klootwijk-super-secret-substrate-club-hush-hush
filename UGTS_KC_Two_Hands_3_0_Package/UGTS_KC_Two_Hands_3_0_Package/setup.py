from setuptools import find_packages, setup

setup(
    name="ugts-kc-two-hands",
    version="3.0.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    description="UGTS-KC Two Hands 3.0 reference scene, geometry, interaction and replay runtime",
    python_requires=">=3.10",
)
