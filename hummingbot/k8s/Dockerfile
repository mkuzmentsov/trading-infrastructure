FROM hummingbot/hummingbot:latest

# WhiteBIT connector is not in the official Hummingbot image.
# We copy it from the WhiteBIT community fork:
# https://github.com/whitebit-exchange/hummingbot
#
# The connector files land in the standard connectors directory
# so Hummingbot discovers them automatically.

USER root

RUN apt-get update -qq && apt-get install -y --no-install-recommends git && \
    git clone --depth 1 https://github.com/whitebit-exchange/hummingbot /tmp/wb-hummingbot && \
    cp -r /tmp/wb-hummingbot/hummingbot/connector/exchange/whitebit \
          /home/hummingbot/hummingbot/connector/exchange/ && \
    rm -rf /tmp/wb-hummingbot && \
    apt-get remove -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /home/hummingbot/entrypoint.sh
RUN chmod +x /home/hummingbot/entrypoint.sh

USER hummingbot

ENTRYPOINT ["/home/hummingbot/entrypoint.sh"]
