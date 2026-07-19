"""Compatibility build metadata for Python 3.9 environments with older pip frontends."""

from setuptools import find_packages, setup


setup(
    name="loop-marketing-runtime",
    version="2.0.0.dev0",
    description="Host-neutral local runtime for Loop Marketing v2",
    python_requires=">=3.9",
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=[],
    entry_points={"console_scripts": ["loop-marketing=loop_marketing_runtime.cli:main"]},
    data_files=[
        ("share/loop-marketing-runtime/contracts", [
            "contracts/state-schema.json",
            "contracts/event-schema.json",
            "contracts/handoff-schema.json",
        ]),
        ("share/loop-marketing-runtime/data", [
            "data/tactic-catalog.json",
            "data/relationship-map.json",
            "data/role-matrix.json",
            "data/routing-contract.json",
        ]),
        ("share/loop-marketing-runtime/adapters", ["adapters/adapter-contract.json"]),
    ],
)
