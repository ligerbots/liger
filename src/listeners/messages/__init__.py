import re
from slack_bolt import App
from .messages import sayBots, attendancePoll, sendAttendancePoll

# To receive messages from a channel or dm your app must be a member!


def register(app: App):
    # app.message(re.compile("Liger", re.I))(sayBots)
    # app.message(re.compile("When I say Liger you say", re.I))(sayBots)
    app.message(re.compile("send attendance poll"))(sendAttendancePoll)
    app.message(re.compile("poll test"))(attendancePoll)
