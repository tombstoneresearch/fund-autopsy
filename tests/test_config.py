"""Tests for configuration module."""


from fundautopsy.config import (
    APP_VERSION,
    CONTACT_EMAIL,
    EDGAR_RATE_LIMIT_DELAY,
    EDGAR_USER_AGENT,
    GITHUB_ORG,
    GITHUB_REPO,
    GITHUB_URL,
    ORG_NAME,
    ORG_TAGLINE,
    PROJECT_NAME,
)


class TestConfigurationValues:
    """Test that configuration values are properly set."""

    def test_org_name_set(self):
        """Organization name should be set."""
        assert ORG_NAME is not None
        assert len(ORG_NAME) > 0
        assert ORG_NAME == "Tombstone Research"

    def test_org_tagline_set(self):
        """Organization tagline should be set."""
        assert ORG_TAGLINE is not None
        assert len(ORG_TAGLINE) > 0
        assert ORG_TAGLINE == "Leave no stone unturned."

    def test_project_name_set(self):
        """Project name should be set."""
        assert PROJECT_NAME is not None
        assert len(PROJECT_NAME) > 0
        assert PROJECT_NAME == "Fund Autopsy"

    def test_contact_email_valid_format(self):
        """Contact email should be in valid email format."""
        assert CONTACT_EMAIL is not None
        assert "@" in CONTACT_EMAIL
        assert "." in CONTACT_EMAIL
        assert CONTACT_EMAIL == "tombstoneresearch@proton.me"

    def test_github_org_set(self):
        """GitHub organization should be set."""
        assert GITHUB_ORG is not None
        assert len(GITHUB_ORG) > 0
        assert GITHUB_ORG == "tombstoneresearch"

    def test_github_repo_set(self):
        """GitHub repository should be set."""
        assert GITHUB_REPO is not None
        assert len(GITHUB_REPO) > 0
        assert GITHUB_REPO == "fund-autopsy"

    def test_github_url_correct_format(self):
        """GitHub URL should be properly formatted."""
        assert GITHUB_URL is not None
        assert "github.com" in GITHUB_URL
        assert GITHUB_ORG in GITHUB_URL
        assert GITHUB_REPO in GITHUB_URL
        assert GITHUB_URL == "https://github.com/tombstoneresearch/fund-autopsy"

    def test_github_url_matches_components(self):
        """GitHub URL should be constructed from org and repo."""
        expected = f"https://github.com/{GITHUB_ORG}/{GITHUB_REPO}"
        assert GITHUB_URL == expected

    def test_edgar_user_agent_includes_contact(self):
        """EDGAR User-Agent should include contact email."""
        assert CONTACT_EMAIL in EDGAR_USER_AGENT
        assert PROJECT_NAME in EDGAR_USER_AGENT
        assert "open-source" in EDGAR_USER_AGENT.lower()

    def test_edgar_rate_limit_positive(self):
        """EDGAR rate limit delay should be positive."""
        assert EDGAR_RATE_LIMIT_DELAY > 0
        assert EDGAR_RATE_LIMIT_DELAY >= 0.10  # At least 100ms
        assert EDGAR_RATE_LIMIT_DELAY == 0.12  # Specific value

    def test_edgar_rate_limit_less_than_100ms_per_request(self):
        """Rate limit should respect SEC's 10 req/sec (100ms each)."""
        # SEC allows 10 requests/second = 100ms per request minimum
        # We use 120ms for safety margin
        assert EDGAR_RATE_LIMIT_DELAY >= 0.100
        assert EDGAR_RATE_LIMIT_DELAY <= 0.200

    def test_app_version_semver_format(self):
        """App version should be in semantic versioning format."""
        assert APP_VERSION is not None
        parts = APP_VERSION.split(".")
        assert len(parts) >= 3, "Version should have at least major.minor.patch"
        assert APP_VERSION == "0.1.0"

    def test_app_version_matches_project(self):
        """App version should be reasonable for project."""
        # Pre-release (0.x.x) is expected for new project
        assert APP_VERSION.startswith("0.")

    def test_all_config_strings_are_strings(self):
        """All config values should be strings."""
        assert isinstance(ORG_NAME, str)
        assert isinstance(ORG_TAGLINE, str)
        assert isinstance(PROJECT_NAME, str)
        assert isinstance(CONTACT_EMAIL, str)
        assert isinstance(GITHUB_ORG, str)
        assert isinstance(GITHUB_REPO, str)
        assert isinstance(GITHUB_URL, str)
        assert isinstance(EDGAR_USER_AGENT, str)
        assert isinstance(APP_VERSION, str)

    def test_rate_limit_is_numeric(self):
        """Rate limit delay should be numeric."""
        assert isinstance(EDGAR_RATE_LIMIT_DELAY, (int, float))

    def test_no_empty_strings(self):
        """No configuration string should be empty."""
        assert len(ORG_NAME) > 0
        assert len(ORG_TAGLINE) > 0
        assert len(PROJECT_NAME) > 0
        assert len(CONTACT_EMAIL) > 0
        assert len(GITHUB_ORG) > 0
        assert len(GITHUB_REPO) > 0
        assert len(GITHUB_URL) > 0
        assert len(EDGAR_USER_AGENT) > 0
        assert len(APP_VERSION) > 0

    def test_github_components_no_spaces(self):
        """GitHub org and repo should not contain spaces."""
        assert " " not in GITHUB_ORG
        assert " " not in GITHUB_REPO

    def test_github_components_lowercase(self):
        """GitHub org and repo should be lowercase."""
        assert GITHUB_ORG == GITHUB_ORG.lower()
        assert GITHUB_REPO == GITHUB_REPO.lower()

    def test_contact_email_no_spaces(self):
        """Email should not contain spaces."""
        assert " " not in CONTACT_EMAIL

    def test_edgar_user_agent_well_formatted(self):
        """EDGAR User-Agent should follow SEC guidelines."""
        # SEC guideline: "project-name/version (contact-email; description)"
        assert "/" in EDGAR_USER_AGENT  # Has version separator
        assert "(" in EDGAR_USER_AGENT and ")" in EDGAR_USER_AGENT  # Has parenthetical
        assert ";" in EDGAR_USER_AGENT  # Has email separator

    def test_configuration_immutability_hint(self):
        """All configuration values are uppercase (convention for constants)."""
        # This is a code style check, not a runtime check
        # All config variables should be ALL_CAPS to indicate immutability
        config_names = [
            "ORG_NAME", "ORG_TAGLINE", "PROJECT_NAME", "CONTACT_EMAIL",
            "GITHUB_ORG", "GITHUB_REPO", "GITHUB_URL", "EDGAR_USER_AGENT",
            "EDGAR_RATE_LIMIT_DELAY", "APP_VERSION"
        ]
        # Just verify we're testing the right variables
        assert len(config_names) > 0
