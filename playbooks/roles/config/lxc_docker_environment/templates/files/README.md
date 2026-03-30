# Template Files for LXC Internal Setup

This directory contains template files and folders that will be copied or rendered into the LXC containers.

## Directory Structure

```
files/
├── dockge/               # Dockge Docker Compose configuration
│   └── compose.yml       # Example compose file for Dockge
├── admin/                # Service-agent admin stack templates
│   ├── .env.j2           # Rendered from inventory variables
│   └── compose.yml.j2    # Rendered admin stack compose file
└── example-app/          # Example application structure
    └── compose.yml       # Example application compose file
```

## Usage

Place your template files and directories in this `files/` folder. Static files are copied to `/shared/{{ inventory_hostname }}/`, and files ending in `.j2` are rendered from inventory variables before being written.

### For Dockge

The `dockge/` folder should contain:
- `compose.yml` - Docker Compose configuration for Dockge itself
- Any other configuration files Dockge needs

### For Your Applications

Create additional folders for other applications you want to deploy:
```
files/
├── dockge/
├── myapp/
│   ├── compose.yml
│   └── .env
└── another-app/
    └── compose.yml
```

## File Ownership

All files copied to `/shared/{{ inventory_hostname }}/` will be owned by UID:GID `1001:1001` by default.
This can be customized via the `lxc_internal_shared_owner` and `lxc_internal_shared_group` variables.

## Template Variables

You can use Jinja2 template variables in any file with `.j2` extension:
```
files/
└── dockge/
    ├── compose.yml.j2    # Will be templated
    └── config.json       # Will be copied as-is
```

Variables available:
- `{{ inventory_hostname }}` - Container hostname
- `{{ ansible_host }}` - Container IP address
- Any other Ansible variables from your inventory
