import pytest

from ehrm.browser.character_captcha import CharacterCaptchaRecognizer


class FakeOcr:
    def __init__(self, value: str) -> None:
        self.value = value

    def classification(self, _image: bytes) -> str:
        return self.value


def test_character_captcha_normalizes_four_alphanumeric_characters() -> None:
    recognizer = CharacterCaptchaRecognizer(lambda: FakeOcr(" y-3 z7 "))

    assert recognizer.recognize(b"image") == "Y3Z7"


def test_character_captcha_rejects_invalid_length() -> None:
    recognizer = CharacterCaptchaRecognizer(lambda: FakeOcr("123"))

    with pytest.raises(ValueError, match="应为 4 位"):
        recognizer.recognize(b"image")
