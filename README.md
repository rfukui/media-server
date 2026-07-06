# Home Server Stack

This repository contains a self-hosted home server focused on local media, downloads, photo backup, DNS services, and lightweight server administration.

The main stack is built around Docker Compose and exposes its applications behind a single `nginx` entrypoint. It is designed for a personal or family LAN setup rather than a multi-tenant public service.

## What This Project Includes

The primary stack in `compose.yaml` runs:

- [`nginx`](https://github.com/nginx/nginx) as the main reverse proxy
- [`Jellyfin`](https://github.com/jellyfin/jellyfin) for media streaming
- [`Jellyseerr`](https://github.com/Fallenbagel/jellyseerr) for media requests
- [`Transmission`](https://github.com/transmission/transmission) for downloads
- [`Radarr`](https://github.com/Radarr/Radarr), [`Sonarr`](https://github.com/Sonarr/Sonarr), and [`Lidarr`](https://github.com/Lidarr/Lidarr) for media automation
- [`Prowlarr`](https://github.com/Prowlarr/Prowlarr) and [`FlareSolverr`](https://github.com/FlareSolverr/FlareSolverr) for indexer/search support
- [`Homepage`](https://github.com/gethomepage/homepage) for a simple landing/dashboard page
- [`Immich`](https://github.com/immich-app/immich) for photo and video backup
- [`Portainer`](https://github.com/portainer/portainer) and [`Yacht`](https://github.com/SelfhostedPro/Yacht) for Docker administration
- [`Pi-hole`](https://github.com/pi-hole/pi-hole) for network-wide DNS filtering

## Repository Layout

- `compose.yaml`: main application stack
- `deploy.sh`: deploy helper for the remote host
- `stack.env`: container environment shared by services in the main stack
- `nginx/nginx.conf`: reverse proxy configuration
- `www/index.html`: server landing page
- `.env`: local deploy-time variables and template values
- `.env.example`: documented example of the required local variables

## What You Need To Run It

### Software

- Linux host
- Docker Engine
- Docker Compose plugin
- `ssh`
- `scp`
- `sshpass`
- `sudo` on the remote host for directory creation and permission fixes
- `deploy.sh` can also attempt to install missing local and remote dependencies automatically (Docker/Compose on remote, and `sshpass`, `ssh`, `scp`, `python3` locally) when package managers are available.

### Network

- A stable LAN address or a stable DNS name pointing to the server
- Port `80/tcp` available for the main `nginx` gateway
- A working network interface for Pi-hole `macvlan`
- Local DNS planning if you want `Pi-hole` to be used by other machines on the network

### Storage

You should expect persistent storage needs to grow quickly.

Minimum practical allocation:

- 100 GB if you are only testing the stack
- 500 GB to 1 TB for a small real media library
- 2 TB+ if you plan to keep movies, series, music, and photo backups on the same host

SSD storage is strongly recommended for:

- Docker volumes
- app databases
- metadata
- caches
- photo library indexing

Large media libraries can live on HDDs, but the application data should stay on SSD if possible.

## Recommended Computer

This stack can run on modest hardware, but the right machine depends on whether you only host services or also transcode media and index large libraries.

### Minimum Reasonable Machine

Suitable for:

- 1 to 2 users
- direct-play media
- small photo library
- light automation

Recommended:

- 4 CPU cores
- 8 GB RAM
- 256 GB SSD for system and app data
- additional media storage as needed

### Recommended General-Purpose Machine

Suitable for:

- small household use
- multiple services running all the time
- moderate media automation
- photo backup with Immich
- occasional transcoding

Recommended:

- 6 to 8 CPU cores
- 16 GB RAM
- 500 GB SSD for OS, Docker, databases, and caches
- 1 TB to several TB of separate media storage

This is the best target for most users of this repository.

### Better Machine For Heavy Use

Suitable for:

- several concurrent users
- larger Jellyfin libraries
- larger Immich libraries
- more background indexing
- more aggressive download automation

Recommended:

- 8+ modern CPU cores
- 32 GB RAM
- SSD/NVMe for app data
- large dedicated media disks
- integrated GPU or supported hardware video acceleration if you expect transcoding

## Important Operational Notes

- This project assumes persistent data directories already exist or will be created on the remote host.
- The deploy flow is template-driven from the local `.env` file.
- `stack.env` is used by containers inside the main compose stack. It is not a replacement for the local deploy-time `.env`.
- Pi-hole uses `macvlan`, which means the host itself may not be able to reach the Pi-hole IP directly even when the container is healthy.

## Deployment Model

The intended workflow is:

1. Fill in `.env` from `.env.example`.
2. Review the template values for network, storage, and host paths.
3. Run `./deploy.sh` to upload files only.
4. Run `./deploy.sh mediaserver` or `./deploy.sh all` to upload and start the stack.

## Who This Is For

This repository is appropriate if you want:

- a personal media and home-services server
- path-based reverse proxying behind a single local URL
- a Docker-first setup
- a deployable configuration for a specific remote Linux machine

It is not structured like a generic turnkey product. It is an opinionated, working home-server repository intended to be adapted to one environment.
