from setuptools import setup, find_packages
setup(name='ugts-kc', version='2.0.0', package_dir={'':'src'}, packages=find_packages('src'),
      description='UGTS-KC 2.0 reference geometry, topology, kinematics and dynamics package',
      python_requires='>=3.10')
