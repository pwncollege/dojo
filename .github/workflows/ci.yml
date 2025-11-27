name: DOJO CI
on:
  workflow_dispatch:
  pull_request:
  push:
    branches:
      - master
  schedule:
    - cron: "42 06 * * *"
jobs:
  test:
    name: "${{ matrix.mode }} DOJO Test"
    runs-on: ubuntu-latest
    timeout-minutes: 40
    strategy:
      matrix:
        mode: [singlenode, multinode]
      fail-fast: false
    steps:
      - name: enable cache saving
        if: matrix.mode == 'singlenode' && (github.event_name == 'schedule' || github.event_name == 'workflow_dispatch')
        run: |
          echo "SAVE_CACHE=yes" >> "$GITHUB_ENV"

      - name: enable cache loading
        if: env.SAVE_CACHE != 'yes' && !(github.event_name == 'schedule' || github.event_name == 'workflow_dispatch')
        run: |
          echo "LOAD_CACHE=yes" >> "$GITHUB_ENV"

      - uses: actions/checkout@v4

      - name: Host information
        run: |
          echo "::group::Host information"
          echo "Hostname: $(hostname)"
          echo "OS: $(lsb_release -d | cut -f2)"
          echo "Kernel: $(uname -r)"
          echo "Architecture: $(uname -m)"
          echo "IP: $(hostname -I)"
          echo "::endgroup::"
          echo "::group::Repo"
          pwd
          git log </dev/null | head -n20
          echo "::endgroup::"
          echo "::group::df -h"
          df -h
          echo "::endgroup::"
          echo "::group::free -h"
          free -h
          echo "::endgroup::"
          echo "::group::lscpu"
          lscpu
          echo "::endgroup::"
          echo "::group::docker images"
          docker images
          echo "::endgroup::"

      - uses: docker/setup-buildx-action@v3

      - name: Free up more disk space
        if: ${{ !env.ACT }}
        run: |
          echo "::group::Initial disk usage"
          df -h
          echo "::endgroup::"

          echo "::group::Cleaning up disk space"
          sudo rm -rf /usr/share/dotnet /usr/local/lib/android /opt/ghc /usr/local/share/boost /opt/hostedtoolcache /usr/local/lib/azure-cli
          sudo apt-get clean
          docker system prune -a -f

          echo "::endgroup::"
          echo "::group::Final disk usage"
          df -h
          echo "::endgroup::"

      - name: Restore docker and workspace cache
        if: env.LOAD_CACHE == 'yes'
        uses: actions/cache/restore@v4
        with:
          path: |
            /tmp/dojo-cache.img
          key: dojo-cache2-${{ matrix.mode }}-${{ github.run_id }}
          restore-keys: |
            dojo-cache2-

      - name: Setup cache filesystem
        run: |
          set -x
          df -h
          if [ "${{ env.ACT }}" == "true" ]; then
            echo "Not using a loopback mount for local CI..."
            sudo apt-get update && sudo apt-get install -y iproute2
          elif [ "$SAVE_CACHE" == "yes" -o ! -e /tmp/dojo-cache.img ]; then
            echo "Creating fresh loopback filesystem image..."
            sudo fallocate -l 9.8G /tmp/dojo-cache.img
            sudo mkfs.btrfs -L cache /tmp/dojo-cache.img
            sudo mount -o loop,compress=zstd:9 /tmp/dojo-cache.img /mnt/
          else
            echo "Using cached loopback filesystem image"
            truncate -s +20G /tmp/dojo-cache.img
            sudo mount -o loop,compress=zstd:6 /tmp/dojo-cache.img /mnt/
            sudo btrfs filesystem resize max /mnt
          fi

          sudo chown $USER:$USER /mnt/

          if [ -e /mnt/dojo-docker -a "${{ matrix.mode }}" = "multinode" ]; then
            sudo cp -a /mnt/dojo-docker /mnt/dojo-docker-node1
            sudo cp -a /mnt/dojo-docker /mnt/dojo-docker-node2
          fi

          mkdir -p /mnt/outer-cache
          mkdir -p /mnt/test-cache

      - name: Build (and cache) outer docker image
        if: env.SAVE_CACHE == 'yes' && !env.ACT
        uses: docker/build-push-action@v5
        with:
          context: .
          tags: pwncollege/dojo
          load: true
          cache-from: type=local,src=/mnt/outer-cache
          cache-to: type=local,dest=/tmp/outer-cache-new,mode=max

      - name: Build (and cache) test docker image
        if: env.SAVE_CACHE == 'yes' && !env.ACT
        uses: docker/build-push-action@v5
        with:
          context: test
          tags: dojo-test
          load: true
          cache-from: type=local,src=/mnt/test-cache
          cache-to: type=local,dest=/tmp/test-cache-new,mode=max

      - name: Build outer docker image
        if: env.SAVE_CACHE != 'yes' && !env.ACT
        uses: docker/build-push-action@v5
        with:
          context: .
          tags: pwncollege/dojo
          load: true
          cache-from: type=local,src=/mnt/outer-cache

      - name: Build test docker image
        if: env.SAVE_CACHE != 'yes' && !env.ACT
        uses: docker/build-push-action@v5
        with:
          context: test
          tags: dojo-test
          load: true
          cache-from: type=local,src=/mnt/test-cache

      - name: Clean up after docker build
        run: |
          if [ "$SAVE_CACHE" == "yes" ]; then
            sudo rm -rf /mnt/outer-cache /mnt/test-cache
            sudo mv /tmp/outer-cache-new /mnt/outer-cache
            sudo mv /tmp/test-cache-new /mnt/test-cache
          fi
          docker images
          df -h
          if [ "${{ env.ACT }}" != "true" ]; then
            docker images | grep "^pwncollege/dojo "
            docker images | grep "^dojo-test "
          fi

      - name: Start the dojo in ${{ matrix.mode }} mode
        timeout-minutes: 15
        run: |
          ./deploy.sh -g -D /mnt/dojo-docker -W /mnt/dojo-workspace ${{ matrix.mode == 'multinode' && '-M' || '' }} -C

      - name: Run ${{ matrix.mode }} dojo tests
        timeout-minutes: 15
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          if [ "${{ matrix.mode }}" = "singlenode" ]
          then
            ./deploy.sh -N -g -t -C
          elif [ "${{ matrix.mode }}" = "multinode" ]
          then
            ./deploy.sh -N -g -t -M
          fi

      - name: Upload coverage reports to Codecov
        if: matrix.mode == 'singlenode'
        uses: codecov/codecov-action@v5
        with:
          token: ${{ secrets.CODECOV_TOKEN }}

      - name: Output logs
        if: always()
        run: |
          echo "::group::Host docker ps"
          docker ps
          echo "::endgroup::"
          echo "::group::Host logs"
          journalctl -u '*' -b
          echo "::endgroup::"
          echo "::group::Main node systemd logs"
          docker exec dojo journalctl -u '*' -b || echo "No main outer container..."
          echo "::endgroup::"
          echo "::group::Main node compose logs"
          docker exec dojo dojo compose logs || echo "No main outer container..."
          echo "::endgroup::"
          if [ "${{ matrix.mode }}" = "multinode" ]; then
            echo "::group::Workspace node 1 systemd logs"
            docker exec dojo-node1 journalctl -u '*' -b || echo "No node1 outer container..."
            echo "::endgroup::"
            echo "::group::Workspace node 1 compose logs"
            docker exec dojo-node1 dojo compose logs || echo "No node1 outer container..."
            echo "::endgroup::"
            echo "::group::Workspace node 2 systemd logs"
            docker exec dojo-node2 journalctl -u '*' -b || echo "No node2 outer container..."
            echo "::endgroup::"
            echo "::group::Workspace node 2 compose logs"
            docker exec dojo-node2 dojo compose logs || echo "No node2 outer container..."
            echo "::endgroup::"
          fi

      - name: Prepare the cache
        if: env.SAVE_CACHE == 'yes'
        run: |
          ./deploy.sh -K -g
          df -h
          sudo umount /mnt/
          du -sm /tmp/dojo-cache.img

      - name: Save docker and workspace cache
        if: env.SAVE_CACHE == 'yes'
        uses: actions/cache/save@v4
        with:
          path: |
            /tmp/dojo-cache.img
          key: dojo-cache2-${{ matrix.mode }}-${{ github.run_id }}

      - name: Final filesystem information
        if: always()
        run: |
          echo "::group::Filesystem"
          df -h
          echo "::endgroup::"

  upload:
    name: Upload Artifacts
    runs-on: ubuntu-latest
    needs: test
    if: github.ref == 'refs/heads/master'
    steps:
      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          push: true
          tags: pwncollege/dojo:latest
