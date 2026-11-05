"""The tickets repository's real workflow configuration."""

from tools.workflow import config


REPOSITORY = "sh4i-yurei/platform-tickets"
TICKET = {
    "color": "D93F0B",
    "description": "An alert from the platform, opened and closed by the ticket band",
}
PLATFORM = {"owner": "sh4i-yurei", "number": 3}


def test_platform_tickets_has_only_its_ticket_label():
    _, _, _, repository_labels = config.load()

    assert repository_labels.get(REPOSITORY) == {"ticket": TICKET}


def test_platform_tickets_uses_the_platform_board():
    boards = config.load_boards()

    assert boards.get(REPOSITORY) == PLATFORM
    assert boards.get(REPOSITORY) == boards["sh4i-yurei/keepbreathing-infra"]


def test_ticket_is_not_a_global_label():
    _, _, global_labels, repository_labels = config.load()

    assert "ticket" not in global_labels
    assert all(
        "ticket" not in labels
        for repo, labels in repository_labels.items()
        if repo != REPOSITORY
    )
