def docker_network_ip_owners(network_documents, ip_address):
    if not isinstance(network_documents, list) or len(network_documents) != 1:
        raise ValueError("Docker network inspection must contain exactly one network")
    network = network_documents[0]
    if not isinstance(network, dict):
        raise ValueError("Docker network inspection contains an invalid network")
    containers = network.get("Containers")
    if containers is None:
        return []
    if not isinstance(containers, dict):
        raise ValueError("Docker network inspection contains invalid containers")
    owners = []
    for container_id, endpoint in containers.items():
        if not isinstance(container_id, str) or not isinstance(endpoint, dict):
            raise ValueError("Docker network inspection contains an invalid endpoint")
        endpoint_address = endpoint.get("IPv4Address")
        if not isinstance(endpoint_address, str):
            raise ValueError(
                "Docker network inspection contains an invalid IPv4 address"
            )
        if endpoint_address.partition("/")[0] != ip_address:
            continue
        name = endpoint.get("Name")
        owners.append(name if isinstance(name, str) and name else container_id)
    return sorted(owners)


def is_transient_docker_ip_allocation_error(stderr):
    message = stderr.lower()
    return "address already in use" in message or "is already allocated" in message
