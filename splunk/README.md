# Splunk Configuration for DOJO

This configuration adds Splunk to the DOJO infrastructure to capture logs from all containers.

## Setup

1. The Splunk container is configured in `docker-compose.yml` with:
   - Web interface on port 8001 (to avoid conflict with CTFd on port 8000)
   - HEC (HTTP Event Collector) on port 8088
   - Management API on port 8089

2. When enabled, all containers send logs to Splunk via the Docker logging driver configured at the daemon level.

3. Default credentials:
   - Username: `admin`
   - Password: `DojoSplunk2024!`

4. HEC Token: `11111111-1111-1111-1111-111111111111`

## Enabling Splunk

1. Set `ENABLE_SPLUNK=true` in `/data/config.env` before starting the DOJO

2. Start the DOJO normally:
   ```bash
   docker run --privileged -v /path/to/data:/data pwncollege/dojo
   ```

3. The Splunk container will start automatically and Docker will be configured to send all logs to it

## Testing

Once Splunk is enabled and the DOJO is running:

1. Access Splunk Web UI at `http://localhost:8001`

2. Search for logs:
   ```
   index=main source="docker"
   ```

## Outer Container Logs

To enable Splunk logging for the outer DOJO container:

1. Set `ENABLE_SPLUNK=true` in `/data/config.env` before starting the DOJO

2. Start (or restart) the DOJO container

The Docker daemon will be automatically configured to send all container logs to Splunk. This configuration is applied during container initialization before Docker starts.

## Troubleshooting

1. Check Splunk is receiving data:
   ```bash
   curl -k -u admin:DojoSplunk2024! http://localhost:8089/services/data/inputs/http
   ```

2. Test HEC endpoint:
   ```bash
   curl -k http://localhost:8088/services/collector/event \
     -H "Authorization: Splunk 11111111-1111-1111-1111-111111111111" \
     -d '{"event": "test event", "sourcetype": "manual"}'
   ```

3. Check container logs are configured correctly:
   ```bash
   docker inspect <container_name> | grep -A 10 LogConfig
   ```