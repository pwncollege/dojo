#define FUSE_USE_VERSION 30

#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <dirent.h>
#include <limits.h>

#include <fuse.h>

static int workspace_accessible()
{
    uid_t uid = fuse_get_context()->uid;
    gid_t gid = fuse_get_context()->gid;
    return uid == 1000 || uid == gid;
}

static int workspace_exists(const char *path, char *real_path)
{
    snprintf(real_path, PATH_MAX, "/run/dojo/bin%s", path);
    struct stat real_stat;
    return stat(real_path, &real_stat) == 0;
}

static int workspace_getattr(const char *path, struct stat *stbuf)
{
    if (strcmp(path, "/") == 0) {
        stbuf->st_mode = S_IFDIR | 0755;
        stbuf->st_nlink = 2;
        return 0;
    }

    char real_path[PATH_MAX];
    if (!workspace_accessible() || !workspace_exists(path, real_path))
        return -ENOENT;

    memset(stbuf, 0, sizeof(struct stat));
    stbuf->st_mode = S_IFLNK | 0777;
    stbuf->st_nlink = 1;
    stbuf->st_uid = 0;
    stbuf->st_gid = 0;
    stbuf->st_size = strlen(real_path);
    return 0;
}

static int workspace_readdir(const char *path, void *buf, fuse_fill_dir_t filler, off_t offset, struct fuse_file_info *fi)
{
    if (strcmp(path, "/") != 0) {
        return -ENOENT;
    }

    filler(buf, ".", NULL, 0);
    filler(buf, "..", NULL, 0);

    if (!workspace_accessible())
        return 0;

    DIR *dp = opendir("/run/dojo/bin");
    if (dp == NULL)
        return -errno;

    struct dirent *de;
    while ((de = readdir(dp)) != NULL) {
        struct stat st;
        memset(&st, 0, sizeof(st));
        st.st_ino = de->d_ino;
        st.st_mode = S_IFLNK | 0777;
        if (filler(buf, de->d_name, &st, 0))
            break;
    }
    closedir(dp);

    return 0;
}

static int workspace_readlink(const char *path, char *buf, size_t size)
{
    char real_path[PATH_MAX];
    if (!workspace_accessible() || !workspace_exists(path, real_path))
        return -ENOENT;

    snprintf(buf, size, "%s", real_path);
    return 0;
}

static struct fuse_operations workspace_operations = {
    .getattr  = workspace_getattr,
    .readdir  = workspace_readdir,
    .readlink = workspace_readlink,
};

int main(int argc, char *argv[])
{
    return fuse_main(argc, argv, &workspace_operations, NULL);
}
