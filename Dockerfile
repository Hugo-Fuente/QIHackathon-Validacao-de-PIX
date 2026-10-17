FROM python:3.11-slim AS base

# A aplicação roda com usuário sem privilégios.
RUN adduser --system --no-create-home user

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copiar o requirements antes do código preserva o cache das dependências.
COPY requirements.txt /requirements.txt
RUN pip install --upgrade pip && pip install -r /requirements.txt

WORKDIR /app
COPY src /app

FROM base AS api
RUN chown -R user /app
USER user

# --no-server-header: não expõe a versão do uvicorn.
CMD uvicorn app:app --host 0.0.0.0 --port 3000 --no-server-header
