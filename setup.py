from setuptools import setup, find_packages


requirements = open('requirements.txt').readlines()
dependency_links = [r for r in requirements if r.startswith('git+')]
install_requires = [r for r in requirements if not r.startswith('git+')]
tests_require = open('tests/requirements.txt').readlines()


setup(
    name = 'core',
    version = '1.0.0',
    description = 'Scitran Core API',
    author = 'Gunnar Schaefer',
    author_email = 'gsfr@flywheel.io',
    maintainer = 'Megan Henning, Ambrus Simon',
    maintainer_email = 'meganhenning@flywheel.io, ambrussimon@invenshure.com',
    url = 'https://github.com/scitran/core',
    license = 'MIT',
    packages = find_packages(),
    dependency_links = dependency_links,
    install_requires = install_requires,
    tests_require = tests_require,
)
