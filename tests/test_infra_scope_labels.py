"""The infrastructure repository's real scope label configuration."""

from tools.workflow import config


REPOSITORY = "sh4i-yurei/keepbreathing-infra"


def test_infra_iac_scope_has_exact_definition():
    _, _, _, repository_labels = config.load()

    assert repository_labels[REPOSITORY].get("scope:iac") == {
        "color": "C5DEF5",
        "description": "Area: machines/, packer/ and tofu/",
    }


def test_infra_has_exact_scope_names():
    _, _, _, repository_labels = config.load()

    assert sorted(repository_labels[REPOSITORY]) == [
        "scope:access",
        "scope:baseline",
        "scope:ci",
        "scope:hub",
        "scope:iac",
        "scope:node-exporter",
        "scope:staging",
        "scope:tailscale",
        "scope:web",
        "scope:workstation",
    ]
