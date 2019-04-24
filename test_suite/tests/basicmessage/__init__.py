import datetime
from test_suite.message import Message
from test_suite.tests import validate_message


class BasicMessage:
    FAMILY_NAME = "basicmessage"
    VERSION = "1.0"
    FAMILY = "did:sov:BzCbsNYhMrjHiqZDTUASHg;spec/" + FAMILY_NAME + "/" + VERSION + "/"

    MESSAGE = FAMILY + "message"

    @staticmethod
    def build(content: str) -> Message:
        sent_time = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat(' ')
        return Message({
            '@type': BasicMessage.MESSAGE,
            '~l10n': {'locale': 'en'},
            'sent_time': sent_time,
            'content': content
        })

    @staticmethod
    def validate(msg: Message):
        validate_message(
            [
                ('@type', BasicMessage.MESSAGE),
                '~l10n',
                'sent_time',
                'content',
            ],
            msg
        )

        validate_message(
            [
                ('locale', 'en')
            ],
            msg['~l10n']
        )
