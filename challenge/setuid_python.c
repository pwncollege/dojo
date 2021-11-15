#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>

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

    char *python_argv_prefix[] = { "/usr/bin/python", "-I", "--", NULL };
    char **python_argv = malloc(sizeof(python_argv_prefix) + argc * sizeof(char *));
    int python_argc = 0;
    for (int i = 0; python_argv_prefix[i]; i++)
        python_argv[python_argc++] = python_argv_prefix[i];
    python_argv[python_argc++] = path;
    for (int i = 2; i < argc; i++)
        python_argv[python_argc++] = argv[i];
    python_argv[python_argc] = NULL;

    execve(python_argv[0], python_argv, envp);
}
