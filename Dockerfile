FROM python:3.12-slim

WORKDIR /app

COPY thunai_deployment_sentinel/ ./thunai_deployment_sentinel/

EXPOSE 8080

ENTRYPOINT ["python", "-m", "thunai_deployment_sentinel"]
