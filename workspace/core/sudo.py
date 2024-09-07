import os
import pwd
import shutil
import sys


def error(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def main():
    program = os.path.basename(sys.argv[0])

    if not os.path.exists("/run/dojo/var/root/privileged"):
        error(f"{program}: workspace is not privileged")

    struct_passwd = pwd.getpwuid(os.geteuid())
    os.setuid(struct_passwd.pw_uid)
    os.setgid(struct_passwd.pw_gid)
    os.setgroups([])

    if len(sys.argv) < 2:
        error(f"Usage: {program} <command> [args...]")

    command = sys.argv[1]
    command_path = shutil.which(sys.argv[1])
    if not command_path:
        error(f"{program}: {command}: command not found")
    argv = sys.argv[1:]

    try:
        os.execve(command_path, argv, os.environ)
    except:
        os.exit(1)


if __name__ == "__main__":
    main()