#include <stdio.h>
#include <unistd.h>
#include <errno.h>

int main(void)
{
  if (setuid(geteuid())) perror("setuid");
  if (setgid(getegid())) perror("setgid");
  char *argv[] = {"/opt/pwn.college/kernel/launch.sh", 0};
  char *envp[] = {0};
  execve(argv[0], argv, envp);
  perror("execve");
  return errno;
}
