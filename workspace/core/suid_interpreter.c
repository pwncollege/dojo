#define _GNU_SOURCE
#include <linux/limits.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>

#define ERROR_ARGC 1          // Must have argv[1] be script path
#define ERROR_NOT_FOUND 2     // Resolved script path must exist
#define ERROR_PATH 3          // Resolved script path must be in a known-good location (SECURITY: prevent symlink races during further analysis and invocation)
#define ERROR_NOT_ROOT 4      // Resolved script path must be owned by root (we're running root suid!)
#define ERROR_NOT_SUID 5      // Resolved script path must be suid (we're running root suid!)
#define ERROR_BAD_SHEBANG 6   // Resolved script must indicate it's desire to be run with THIS interpreter (SECURITY: prevent weird-behavior due to running incorrect interpreter via non-shebang forced invocation)
#define ERROR_BAD_ENV 7       // Resolved script which indicates a clear environment must have a cleared environment (SECURITY: prevent weird-behavior due to running interpreter with environment via non-shebang forced invocation)

int main(int argc, char **argv, char **envp)
{
    if (argc < 2)
        return ERROR_ARGC;

    char *path = argv[1];
    char path_buf[PATH_MAX];
    char *workspacefs_path = "/run/workspace/bin/";
    if (!strncmp(workspacefs_path, path, strlen(workspacefs_path))) {
        snprintf(path_buf, PATH_MAX, "/run/dojo/bin/%s", path + strlen(workspacefs_path));
        path = path_buf;
    }

    path = realpath(path, NULL);
    if (!path)
        return ERROR_NOT_FOUND;

    char *valid_paths[] = {
        "/challenge/",
        "/opt/pwn.college/",
        "/nix/",
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

    char first_line[PATH_MAX];
    FILE *file = fopen(path, "r");
    fgets(first_line, PATH_MAX, file);
    fclose(file);

#ifdef SUID_PYTHON
    char *child_argv_prefix[] = { "/usr/bin/python", "-I", "--", NULL };
    if (strcmp(first_line, "#!/opt/pwn.college/python\n") &&
        strcmp(first_line, "#!/usr/bin/env python-suid\n"))
        return ERROR_BAD_SHEBANG;
#endif

#ifdef SUID_BASH
    char c_arg[PATH_MAX];
    snprintf(c_arg, PATH_MAX, ". \"%s\"", path);
    char *child_argv_prefix[] = { "/bin/bash", "-c", c_arg, argv[1], NULL };
    setresuid(geteuid(), geteuid(), geteuid());
    setresgid(getegid(), getegid(), getegid());
    unsetenv("BASH_ENV");
    unsetenv("ENV");
    if (!strcmp(first_line, "#!/usr/bin/env -iS /opt/pwn.college/bash\n") ||
        !strcmp(first_line, "#!/usr/bin/env -iS bash-suid\n"))
    {
        if (envp[0] != NULL)
            return ERROR_BAD_ENV;
    }
    else if (strcmp(first_line, "#!/opt/pwn.college/bash\n") &&
             strcmp(first_line, "#!/usr/bin/env bash-suid\n"))
        return ERROR_BAD_SHEBANG;
#endif

#ifdef SUID_SH
    char c_arg[PATH_MAX];
    snprintf(c_arg, PATH_MAX, ". \"%s\"", path);
    char *child_argv_prefix[] = { "/bin/sh", "-c", c_arg, argv[1],  NULL };
    setresuid(geteuid(), geteuid(), geteuid());
    setresgid(getegid(), getegid(), getegid());
    if (!strcmp(first_line, "#!/usr/bin/env -iS /opt/pwn.college/sh\n") ||
        !strcmp(first_line, "#!/usr/bin/env -iS sh-suid\n"))
    {
        if (envp[0] != NULL)
            return ERROR_BAD_ENV;
    }
    else if (strcmp(first_line, "#!/opt/pwn.college/sh\n") &&
             strcmp(first_line, "#!/usr/bin/env sh-suid\n"))
        return ERROR_BAD_SHEBANG;
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
