docker-build:
	-docker build -t indy-agent .. -f Dockerfile

docker-start:
	-docker run -ti -p $$PORT:$$PORT -e PORT=$$PORT -e HOST=$$HOST --name indy-agent_$$PORT indy-agent
	-docker rm indy-agent_$$PORT

# EXAMPLE: make docker-start-detached PORT=8094 HOST=<EXTERNALLY_ACCESSIBLE_IP_OR_HOSTNAME>
docker-start-detached:
	-docker run --rm -dti -p $$PORT:$$PORT -e PORT=$$PORT -e HOST=$$HOST --name indy-agent_$$PORT indy-agent

docker-getip:
	-docker container inspect indy-agent_$$PORT | grep "\"IPAddress\"" | tail -n 1 | sed "s/[IPAddress|:|\"|,| ]//g"
