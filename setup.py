from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

with open("requirements.txt", "r", encoding="utf-8") as f:
    requirements = [
        line.strip() for line in f
        if line.strip() and not line.startswith("#")
    ]

setup(
    name="mimo-borsa-arastirma",
    version="1.0.0",
    author="yasar-afk",
    description="MIMO Borsa Arastirma ve Trading Botu",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yasar-afk/mimo-borsa-arastirma",
    py_modules=["main", "live_v7", "config"],
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=requirements,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Office/Business :: Financial :: Investment",
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    entry_points={
        "console_scripts": [
            "mimo-borsa=main:main",
        ],
    },
)
