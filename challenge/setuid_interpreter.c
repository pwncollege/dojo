#define _GNU_SOURCE
#include <linux/limits.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>

#define ERROR_ARGC 1
#define ERROR_NOT_FOUND 2
#define ERROR_PATH 3
#define ERROR_NOT_ROOT 4
#define ERROR_NOT_SUID 5

int main(int argc, char **argv, char **envp)
{
    if (argc < 2)
        return ERROR_ARGC;

    char *path = realpath(argv[1], NULL);
    if (!path)
        return ERROR_NOT_FOUND;

    char *valid_paths[] = {
        "/challenge/",
        "/opt/pwn.college/",
        NULL
    };
    bool valid = false;
    for (char **valid_path = valid_paths; *valid_path; valid_path++)
        if (!strncmp(*valid_path, path, strlen(*valid_path)))
            valid = true;
    if (!valid)
        return ERROR_PATH;

    struct stat stat = { 0 };
    lstat(path, &stat);
    if (stat.st_uid != 0)
        return ERROR_NOT_ROOT;
    if (!(stat.st_mode & S_ISUID))
        return ERROR_NOT_SUID;

#ifdef SUID_PYTHON
    char *child_argv_prefix[] = { "/usr/bin/python3", "-I", "--", NULL };
#endif
#ifdef SUID_BASH
    char c_arg[PATH_MAX];
    snprintf(c_arg, PATH_MAX, ". \"%s\"", path);
    char *child_argv_prefix[] = { "/usr/bin/bash", "-c", c_arg, argv[1], NULL };
    setresuid(geteuid(), geteuid(), geteuid());
    setresgid(getegid(), getegid(), getegid());
    unsetenv("BASH_ENV");
    unsetenv("ENV");
#endif
#ifdef SUID_SH
    char c_arg[PATH_MAX];
    snprintf(c_arg, PATH_MAX, ". \"%s\"", path);
    char *child_argv_prefix[] = { "/usr/bin/sh", "-c", c_arg, argv[1],  NULL };
    setresuid(geteuid(), geteuid(), geteuid());
    setresgid(getegid(), getegid(), getegid());
#endif

    char **child_argv = malloc(sizeof(child_argv_prefix) + argc * sizeof(char *));
    int child_argc = 0;
    for (int i = 0; child_argv_prefix[i]; i++)
        child_argv[child_argc++] = child_argv_prefix[i];
#ifdef SUID_PYTHON
    child_argv[child_argc++] = path;
#endif
    for (int i = 2; i < argc; i++)
        child_argv[child_argc++] = argv[i];
    child_argv[child_argc] = NULL;

    execve(child_argv[0], child_argv, envp);
}
