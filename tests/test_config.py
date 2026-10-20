import json
import pytest
from insightops.config import configure, configuration_status, load_settings, validate_base_url


def test_local_configuration_and_environment_precedence(tmp_path, monkeypatch):
    path=tmp_path/".env"
    path.write_text('INSIGHTOPS_API_KEY="local-test-value"\nINSIGHTOPS_MODEL="model-a"\nIGNORED=not-executed\n',encoding="utf-8")
    monkeypatch.setenv("INSIGHTOPS_MODEL","model-b")
    settings=load_settings(path)
    assert settings["INSIGHTOPS_MODEL"]=="model-b"
    assert "local-test-value" not in json.dumps(configuration_status(path))
    assert "IGNORED" not in settings


def test_configure_hides_key_and_requires_gitignore(tmp_path,monkeypatch):
    answers=iter(["https://example.com/v1","test-model"])
    monkeypatch.setattr("builtins.input",lambda prompt:next(answers))
    monkeypatch.setattr("insightops.config.getpass.getpass",lambda prompt:"dummy-key-for-test")
    (tmp_path/".gitignore").write_text(".env\n",encoding="utf-8")
    result=configure(tmp_path/".env")
    assert result["ready"]
    assert "dummy-key-for-test" not in json.dumps(result)


@pytest.mark.parametrize("url",["http://example.com/v1","https://user:secret@example.com/v1","https://example.com/v1?key=secret","file:///tmp/model"])
def test_invalid_endpoint_rejected(url):
    with pytest.raises(ValueError):
        validate_base_url(url)
