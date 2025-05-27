# Linux Server Backup Agent

A Python-based backup agent for Linux servers that creates backups of MySQL/MariaDB databases and specified file directories.

## Features

- Backs up MySQL/MariaDB databases using mysqldump
- Backs up specified file directories
- Compresses backups into tar.gz files
- Creates a combined archive containing both database and files backups
- Validates configuration before proceeding
- Detailed logging
- Supports uploading backups to FTP or SFTP servers

## Requirements

- Python 3.6+
- PyYAML package
- MySQL/MariaDB client tools (mysqldump)
- For SFTP support: paramiko package (optional)

## Installation

1. Copy the `main.py` and `config.yaml` files to your server
2. Install required Python packages:

```bash
pip install pyyaml
```

3. For SFTP support, install the paramiko package:

```bash
pip install paramiko
```

4. Make the script executable:

```bash
chmod +x main.py
```

## Configuration

Edit the `config.yaml` file to match your server's configuration:

```yaml
# System Configuration
SYSTEM:
  server_name: "foobar.com"  # Server name to use in backup filenames

# Database Configuration
DB:
  db_type: "mysql"  # Can be "mysql" or "mariadb"
  db_host: "127.0.0.1"
  db_user: "root"  # Optional, defaults to "root"
  db_password: ""  # Optional, defaults to empty string
  db_name: "--all-databases"  # Optional, defaults to "--all-databases"

# Files Configuration
FILES:
  files_dir_path: "/var/www/something/current"

# Backup Destination Configuration
BACKUP:
  destination_type: "ftp"  # Can be "ftp", "sftp", or "local" (default)
  keep_local_copy: true    # Whether to keep a local copy after uploading
  keep_backups: 5          # Number of backups to preserve (older ones will be deleted)

# FTP Configuration (used when destination_type is "ftp")
FTP:
  host: "ftp.example.com"
  port: 21
  username: "ftpuser"
  password: "ftppassword"
  remote_dir: "/backups"
  passive_mode: true

# SFTP Configuration (used when destination_type is "sftp")
SFTP:
  host: "sftp.example.com"
  port: 22
  username: "sftpuser"
  password: ""  # Leave empty if using key-based authentication
  private_key_path: "/path/to/private/key"  # Path to private key for authentication
  remote_dir: "/backups"
```

### Configuration Options

#### SYSTEM Section

- `server_name`: Name of the server to use in backup filenames

#### DB Section

- `db_type`: Database type, either "mysql" or "mariadb"
- `db_host`: Database host address
- `db_user`: (Optional) Database username, defaults to "root"
- `db_password`: (Optional) Database password, defaults to empty string
- `db_name`: (Optional) Database name to backup, defaults to "--all-databases" which backs up all databases

#### FILES Section

- `files_dir_path`: Path to the directory to backup

#### BACKUP Section (Optional)

- `destination_type`: Where to send the backup, can be "local", "ftp", or "sftp"
- `keep_local_copy`: Whether to keep a local copy of the backup after uploading to a remote destination
- `keep_backups`: Number of backups to preserve (older ones will be automatically deleted)

#### FTP Section (Required when destination_type is "ftp")

- `host`: FTP server hostname or IP address
- `port`: (Optional) FTP server port, defaults to 21
- `username`: FTP username
- `password`: FTP password
- `remote_dir`: Directory on the FTP server to store backups
- `passive_mode`: (Optional) Whether to use passive mode, defaults to true

#### SFTP Section (Required when destination_type is "sftp")

- `host`: SFTP server hostname or IP address
- `port`: (Optional) SFTP server port, defaults to 22
- `username`: SFTP username
- `password`: SFTP password (required if not using key-based authentication)
- `private_key_path`: Path to the private key file (required if not using password authentication)
- `remote_dir`: Directory on the SFTP server to store backups

## Usage

Run the backup agent:

```bash
./main.py
```

Or specify a custom configuration file:

```bash
./main.py /path/to/custom-config.yaml
```

## Output

The backup agent creates a combined backup file in the current directory with the naming format:

```
[YYYY-MM-DD.HH:MM]_[server_name]_root_files_and_db.tar.gz
```

This archive contains two files:
1. `[YYYY-MM-DD.HH:MM]_[server_name]_db.tar.gz` - Database backup
2. `[YYYY-MM-DD.HH:MM]_[server_name]_root_files.tar.gz` - Files backup

If a remote destination (FTP or SFTP) is configured, the backup will be uploaded to that destination. You can choose whether to keep a local copy of the backup after uploading by setting the `keep_local_copy` option in the BACKUP section.

The agent also supports backup rotation, which automatically deletes older backups while keeping a specified number of the most recent ones. This applies to both local and remote backups. Set the `keep_backups` option in the BACKUP section to specify how many backups to preserve.

## Logging

Logs are written to both the console and a `backup.log` file in the same directory as the script.

## Automation

To run the backup automatically, you can set up a cron job:

```bash
# Edit crontab
crontab -e

# Add a line to run the backup daily at 2 AM
0 2 * * * cd /path/to/backup/script && ./main.py
