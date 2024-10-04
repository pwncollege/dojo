import argparse
import grp
import os
import pwd
import shutil
import sys


def error(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def main():
    program = os.path.basename(sys.argv[0])

    parser = argparse.ArgumentParser(description="execute a command as another user")
    parser.add_argument("-u", "--user", help="run command as specified user", default="0")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="command to execute")

    args = parser.parse_args()

    privileged = int(open("/run/dojo/sys/workspace/privileged", "r").read())
    if not privileged:
        error(f"{program}: workspace is not privileged")

    for user in pwd.getpwall():
        if args.user in (user.pw_name, str(user.pw_uid)):
            break
    else:
        error(f"{program}: unknown user: {args.user}")

    groups = [group.gr_id for group in grp.getgrall() if user.pw_name in group.gr_mem]
    if user.pw_gid not in groups:
        groups.append(user.pw_gid)

    os.setgid(user.pw_gid)
    os.setgroups(groups)
    os.setuid(user.pw_uid)

    os.environ["HOME"] = user.pw_dir
    os.environ["USER"] = user.pw_name
    os.environ["SHELL"] = user.pw_shell

    if not args.command:
        parser.print_help()
        sys.exit(1)

    command_path = shutil.which(args.command[0])
    if not command_path:
        error(f"{program}: {args.command[0]}: command not found")

    try:
        os.execve(command_path, args.command, os.environ)
    except:
        os.exit(1)


if __name__ == "__main__":
    main()