FROM python:3.12-slim

# Install required packages
RUN pip install --no-cache-dir docker

# Create directory for socket
RUN mkdir -p /var/run/dojo

# Copy socket service script
COPY dojo-socket-service.py /app/dojo-socket-service.py

# Set working directory
WORKDIR /app

# Run the socket service
CMD ["python3", "/app/dojo-socket-service.py"]