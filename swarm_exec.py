#! /usr/bin/python3
# -*- coding: utf-8 -*-

"""Script call containers in Docker Swarm.

This script call all containers in the Docker Swarm filtered by label.
The script works asynchronously so all calls are made at the same time.
This approach significantly reduces the time of execution.

Requirements:
    All swarm nodes should be Docker Machines.

Example:
    ./swarm-exec.py date +%s%N --labels services=echo

https://github.com/binbrayer/swarmServiceExec

"""

from argparse import ArgumentParser
import asyncio
import json
import os
import subprocess
import urllib3

import docker

docker_cert_root_path = '/root/.docker/machine/machines'

# skip certificate verification
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_machines():
    """Get list of all docker machines.

    Returns:
        list of dict (str, str): [{"name":"machine_name", "url":"machine_url"}, ...]

    """
    command = ['docker-machine', 'ls', '--format', '{"name":"{{.Name}}", "url":"{{.URL}}"}']

    response = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = response.stdout.decode()
    output = '[' + ', '.join(output.splitlines()) + ']'
    output = json.loads(output)
    return output


def get_clients(machines):
    """Get DockerClients.

    Args:
        machines (list of dict): [{"name":"machine_name", "url":"machine_url"}, ...]

    Returns:
        list of docker.client.DockerClient

    """
    clients = []
    for machine in machines:
        cert = os.path.join(docker_cert_root_path, machine['name'], 'cert.pem')
        key = os.path.join(docker_cert_root_path, machine['name'], 'key.pem')
        tls_config = docker.tls.TLSConfig(client_cert=(cert, key))
        client = docker.DockerClient(base_url=machine['url'], tls=tls_config)
        clients.append(client)

    return clients


def get_containers(clients, raw_labels):
    """Get Docker containers marked with one of label.

    Args:
        clients (list of docker.DockerClient)
        raw_labels (list of str): ['foo=bar', ...]


    Returns:
        list of docker.models.containers.Container

    """
    labels = parse_labels(raw_labels)
    containers = []
    for client in clients:
        containers += client.containers.list()
    containers = filter_containers(containers, labels)
    containers.sort(key=lambda x: x.name)
    return containers


def parse_labels(raw_labels):
    """Parse labels list.

    Args:
        raw_labels (list of str): ['foo=bar', ...]

    Returns:
        dict (str, str): {"key":"label", ...}

    """
    if not raw_labels:
        return None
    labels = {}
    for label in raw_labels:
        key, value = label.split('=')
        labels[key] = value
    return labels


def filter_containers(containers, labels):
    """Filter containers by labels.

    Args:
        containers (list of docker.models.containers.Container)
        labels (dict of (str, str)): {"key":"label", ...}

    Returns:
        list of docker.models.containers.Container: containers filtered by labels

    """
    def does_container_have_labels(container, labels):
        if not labels:
            return True
        for key, value in labels.items():
            if key not in container.labels.keys() or value != container.labels[key]:
                return False
        return True

    containers = filter(lambda containers: does_container_have_labels(containers, labels), containers)
    return list(containers)


async def call_container(loop, container, command):
    """Execute command on container.

    Parameters:
        container (docker.models.containers.Container)
        command (str)

    Returns:
        tuple (str, str): ("container_name", "result")

    Note:
        The "result" may be dictionary if we got JSON as response, or string. 

    """
    def exec_run():
        return container.exec_run(command, stdout=True, stderr=True, stdin=False)

    response = await loop.run_in_executor(None, exec_run)
    output = response.output.decode()
    # print(container.name, output)  # Uncomment this line to see asynchronous calls in real time.
    try:
        output = json.loads(output)
    except ValueError:
        pass
    return (container.name, output)


def call(containers, command):
    """Call list of containers.

    Parameters:
        containers (list of docker.models.containers.Container)
        command (str)

    Returns:
        dict (str, str): {"container_name", "result", ...}

    """
    loop = asyncio.get_event_loop()
    tasks = [asyncio.ensure_future(call_container(loop, container, args.command)) for container in containers]
    loop.run_until_complete(asyncio.wait(tasks))
    response = dict(task.result() for task in tasks)
    loop.close()
    return response


def args():
    parser = ArgumentParser(description='Execute command in containers in the Swarm. Command for test: "date +%s%N".')
    parser.add_argument('command', nargs='+', help='Command to executed.')
    parser.add_argument('-l', '--labels', nargs='+', help='Labels of containers.Format: com.docker.stack.namespace=somestack')
    args = parser.parse_args()
    return (args)


if __name__ == '__main__':
    args = args()

    machines = get_machines()
    print('\n=== MACHINES ===')
    [print(machine) for machine in machines]

    clients = get_clients(machines)

    containers = get_containers(clients, args.labels)

    result = call(containers, args.command)
    print('\n=== RESULT ===')
    print(json.dumps(result, indent=4))
