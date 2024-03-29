import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from .listeners import register_listeners

# Tokens and secrets are all stored in environment variables
app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
)

# Attach listeners
register_listeners(app)


# Start app
if __name__ == "__main__":
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
