# Docker `service exec`

## Introduction

> one does not simply run `docker service exec ...`

To execute some command in a container you can run `docker exec ...` but you are able to do that only for containers running on that machine. What if we need to do something on all machines in the swarm?

This is a rare problem but if you are in a swarm and need to execute some command in several containers you are in trouble. You can read more about this case in the [issue #27552](https://github.com/moby/moby/issues/27552).

 At first I thought that [HEALTHCHECK](https://docs.docker.com/engine/reference/builder/#healthcheck) may do the trick but `docker inspect` does not contain "Log" (where the result is expected) in a swarm.

The solution was to use ssh but with [Docker Machine](https://docs.docker.com/machine/) overlay. This approach gives us the desired security and flexibility.  

This is a step by step tutorial. I also prepared a simple Python script which can be used as a start point for your own implementation of `docker service exec`.

> **Warning:** This tutorial ignores security at all. You should keep in mind that Docker, Docker API and Docker Swarm are insecure out of the box and you should learn Docker documentation about that.

## Step by Step Tutorial

In the tutorial we will use three VPS servers with Ubuntu 18.04 on board. All steps will be made from one of them called **Host**. We don't need to login manually to the rest, but we should have their credentials.

## Terminology

We provide the following terminology.

* **Host** - Machine from which  we will make all the steps. It can be your computer or a remote server.
* **Manager** - Docker Swarm Manager.
* **Worker** - Docker Swarm Worker.

## Prepare Host Environment

In our case **Host** and **Manager** will be the same machine (one of our VPS).

Install **Docker**, **Docker Compose** and **Docker Machine** on **Host** machine.

> **NB** Keep in mind you don't need to do that on other machines.

```bash
# Install packages to allow apt to use a repository over HTTPS:
sudo apt install -y apt-transport-https ca-certificates curl gnupg-agent software-properties-common

# Add Docker’s official GPG key:
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -

# Use the following command to set up the stable repository and update the apt package index.
sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"

# Install the latest version of Docker CE
sudo apt install -y docker-ce docker-ce-cli containerd.io

# add your user to the "docker" (to use Docker as a non-root use)
sudo usermod -aG docker $USER

# configure Docker to start on boot
sudo systemctl enable docker

# Install Docker Machine
base=https://github.com/docker/machine/releases/download/v0.16.0; curl -L $base/docker-machine-$(uname -s)-$(uname -m) >/tmp/docker-machine; sudo install /tmp/docker-machine /usr/local/bin/docker-machine

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/download/1.24.1/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose; chmod +x /usr/local/bin/docker-compose
```

### Create Docker Machines

We will create three Docker Machines. One of them will be on the **Host** and two others on the left VPS.

> **NB** At first sight it is not necessary to create Docker Machine on the **Host** (and as result connect to oneself over ssh) but we need do it to make our environment consistent, it is very important for future script. We can skip **Host** if we don't plan to call its containers. 

1. Create key pair on **Host**

   ```ssh-keygen -t rsa```

2. Copy key and create Docker Machines on servers (repeat this step for each server). 

    ```bash
    DOCKER_KEY=/root/.ssh/docker_rsa  # path to the just created key
    MACHINE_NAME=manager  # may be any
    MACHINE_USER=root
    MACHINE_IP=185.185.185.10

    ssh-copy-id -i $DOCKER_KEY $MACHINE_USER@$MACHINE_IP

    docker-machine create --driver generic --generic-ip-address=$MACHINE_IP --generic-ssh-key $DOCKER_KEY --generic-ssh-user=$MACHINE_USER $MACHINE_NAME
    ```

**Test:** `docker-machine ls --format "table {{.Name}}\t{{.URL}}"`

> ```
> NAME       URL
> manager    tcp://185.185.185.10:2376
> worker01   tcp://185.185.185.20:2376
> worker02   tcp://185.185.185.30:2376
> ```

You can see **manager** on **Host** URL.

## Initialize the Swarm

1. Initialize the Swarm.

    ```bash
    docker-machine ssh manager "docker swarm init --advertise-addr 185.185.185.10"
    ```

    > ```
    > Swarm initialized: current node (22px1q62njhtxgxiyvhc7eesh) is now a manager.
    >
    > To add a worker to this swarm, run the following command:
    >
    >     docker swarm join --token SWMTKN-1-4lgo3d0ba8sawansgv986jbbr7p0lh1ah35p5g9jedv813uuw8-8d15ze6pjog1jkh3z4uo2bjb9 185.185.185.10:2377
    >
    > To add a manager to this swarm, run 'docker swarm join-token manager' and follow the instructions.
    > ```

2. Add other machines to the swarm as workers.

    ```bash
    MANAGER_HOST=185.185.185.10
    TOKEN=SWMTKN-1-4lgo3d0ba8sawansgv986jbbr7p0lh1ah35p5g9jedv813uuw8-8d15ze6pjog1jkh3z4uo2bjb9
    WORKER_NAME=worker01

    docker-machine ssh $WORKER_NAME docker swarm join --token $TOKEN $MANAGER_HOST:2377
    ```

**Test:** `docker node ls --format "table {{.ID}}\t{{.Hostname}}\t{{.ManagerStatus}}"`

> ```
> ID                          HOSTNAME            MANAGER STATUS
> 22px1q62njhtxgxiyvhc7eesh   manager             Leader
> q6yrd46kik9a0ltjwf8itbohn   worker01
> niqedw0d5sumjoem5a565bgav   worker02
> ```

## Prepare Tools

We will setup two addition containers: **Registry** (to store our images) and **Visualizer** (to visualize our swarm) . Both of them will run on manager node.

#### Setup Docker Registry

**Warning:** this is insecure. In production you should follow the [Deploy a registry server](https://docs.docker.com/registry/deploying/) instruction. Seriously! Do `docker service rm registry` after tests.

```bash
docker service create \
--name registry \
--publish published=5000,target=5000 \
--constraint=node.role==manager \
registry:2
```

**Test:** `curl http://185.185.185.10:5000/v2/`. You should receive `{}` - empty response. It is ok.

#### Setup Docker Visualizer (optionally)

```bash
docker service create \
--name viz \
--publish published=8080,target=8080 \
--constraint=node.role==manager \
--mount=type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock \
dockersamples/visualizer
```

**Test:** Open http://185.185.185.10:8080/ in your browser. You should see containers running on manager.

## Deploy Demo Stack

We will create three simple services: **alfa**, **bravo** and **charlie** based on one image. The only difference between services is environment variable `SERVICE_NAME`  which will contain the corresponding name of the service. The only thing which these services will do is to send greeting message in response to GET request. Example:

```json
{"greeting": "Hello, I'am Alfa."}
```

1. Create following files (I will create them in *swarmServiceExec/swarmEchoServer*):

    **echoServer.py**

   ```python
   #! /usr/bin/python3
   import os
   from aiohttp import web

   MY_NAME = os.environ['SERVICE_NAME'].capitalize()
   
   
   
   async def say_hello(request):
       response = {'greeting': f"Hello, I'am {MY_NAME}."}
       return web.json_response(response)

   app = web.Application()
   app.add_routes([web.get('/', say_hello)])
   web.run_app(app, port=8080)

   ```

   **requirements.txt**

   ```
   aiohttp==3.5.4

   ```

   **Dockerfile**

   ```dockerfile
   FROM python:3.6-alpine
   COPY requirements.txt /app/requirements.txt
   WORKDIR /app
   RUN pip install -r requirements.txt
   COPY echoServer.py /app/service.py
   CMD ["python", "service.py"]

   ```

   **echo-stack.yml**

   ```yaml
   version: '3'
   services:
     alfa:
       image: 127.0.0.1:5000/echo
       environment:
         - SERVICE_NAME=alfa
       ports:
         - "8001:8080"
     bravo:
       image: 127.0.0.1:5000/echo
       environment:
         - SERVICE_NAME=bravo
       ports:
         - "8002:8080"
     charlie:
       image: 127.0.0.1:5000/echo
       environment:
         - SERVICE_NAME=charlie
       ports:
         - "8003:8080"
       deploy:
           replicas: 3

   ```

2. Build the image:

   ```bash
   docker build . --tag 127.0.0.1:5000/echo:latest
   ```

3. Push the image to Registry:

   ```bash
   docker push 127.0.0.1:5000/echo:latest
   ```

   > No you can see **echo** image in the `curl http://185.185.185.10:5000/v2/_catalog` response.

4. Deploy test service:

   ```
   docker stack deploy -c echo-stack.yml echo
   ```

Test: Run `docker stack ls` or open Visualizer ( http://185.185.185.10:8080/) to see demo services.

> ```
> NAME                SERVICES            ORCHESTRATOR
> echo                3                   Swarm
> ```

## The Trick

Now you can run command on any container in the swarm.

1. Inspect you machines.

   ```bash
   docker-machine ls --format "table {{.Name}}\t{{.URL}}"
   ```

   > ```
   > NAME       URL
   > manager    tcp://185.185.185.10:2376
   > worker01   tcp://185.185.185.20:2376
   > worker02   tcp://185.185.185.30:2376
   > ```

2. Get containers on **worker1** 

   ```bash
   docker-machine ssh worker01 'docker container ls --format "table {{.ID}}\t{{.Names}}"'
   ```

   > ```
   > CONTAINER ID        NAMES
   > d8da205b41f1        echo_charlie.3.l1x0dlywh2g46mvheda15vylx
   > a61290d7bc1e        echo_alfa.1.6j6gha7ksfmg9v04kd2ldxr0b
   > ```

3. Get *SERVICE_NAME* of **echo_alfa.1.6j6gha7ksfmg9v04kd2ldxr0b**

   ```bash
   docker-machine ssh worker01 docker exec echo_alfa.1.6j6gha7ksfmg9v04kd2ldxr0b printenv SERVICE_NAME
   ```

   > ```
   > alfa
   > ```

## Final Step - "`service exec`" Script

What we really want is to  be able to execute command simultaneously on all containers in the swarm. To do that we will create Python3 script which does it asynchronously.

```python
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

    responcse = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = responcse.stdout.decode()
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

```

Now we can call:
```bash
./swarm-exec.py printenv SERVICE_NAME -l com.docker.stack.namespace=echo
```

> ```
> === MACHINES ===
> {'name': 'manager', 'url': 'tcp://185.185.185.10:2376'}
> {'name': 'worker01', 'url': 'tcp://185.185.185.20:2376'}
> {'name': 'worker02', 'url': 'tcp://185.185.185.30:2376'}
> 
> === RESULT ===
> {
>     "echo_alfa.1.6j6gha7ksfmg9v04kd2ldxr0b": "alfa\n",
>     "echo_bravo.1.t47pyzgt9g7s7jruwalccog6g": "bravo\n",
>     "echo_charlie.1.eicjs8clbp9ij36uitssj8omq": "charlie\n",
>     "echo_charlie.2.jge0o8a78lzc1sntkjnf6rgcf": "charlie\n",
>     "echo_charlie.3.l1x0dlywh2g46mvheda15vylx": "charlie\n"
> }
> ```
>    

