FROM budtmo/docker-android:emulator_14.0

WORKDIR /opt/emulytix

COPY orchestrator-api/requirements.txt /tmp/orchestrator-requirements.txt
COPY agent-service/requirements.txt /tmp/agent-requirements.txt
RUN python3 -m venv /opt/emulytix/venv \
    && /opt/emulytix/venv/bin/pip install --no-cache-dir -r /tmp/orchestrator-requirements.txt -r /tmp/agent-requirements.txt

COPY --chown=androidusr:androidusr orchestrator-api /opt/emulytix/orchestrator-api
COPY --chown=androidusr:androidusr agent-service /opt/emulytix/agent-service
COPY --chown=androidusr:androidusr web-ui /opt/emulytix/web-ui
COPY --chown=androidusr:androidusr --chmod=755 all-in-one/start.sh /opt/emulytix/all-in-one/start.sh

RUN cd /opt/emulytix/web-ui \
    && npm install \
    && npm run build

ENV EMULYTIX_RUNTIME_MODE=local
ENV PATH="/opt/emulytix/venv/bin:${PATH}"
ENV ORCHESTRATOR_API_PORT=8010
ENV AGENT_SERVICE_PORT=8011
ENV WEB_UI_PORT=3000
ENV WEB_VNC=true
ENV APP_NAME="Emulytix Orchestrator API"
ENV AGENT_SERVICE_URL="http://127.0.0.1:8011"
ENV EMULYTIX_STORAGE_ROOT="/storage"
ENV PUBLIC_ANDROID_STREAM_URL="http://localhost:6080/vnc.html?autoconnect=1&resize=scale&show_dot=1"
ENV ANDROID_STREAM_PROVIDER="novnc"

EXPOSE 3000 6080 8010 8011 5554 5555

ENTRYPOINT ["/bin/bash", "/opt/emulytix/all-in-one/start.sh"]
