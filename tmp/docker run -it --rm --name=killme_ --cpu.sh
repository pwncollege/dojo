docker run -it --rm --name=killme_ --cpus=4 --memory=4G pwncollege-challenge bash

for i in $(seq 10 20); do
    docker run --rm --name=killme_$i --cpus=4 --memory=4G pwncollege-challenge sh -c '/opt/pwn.college/docker-entrypoint.sh; vm start; sleep 600' &
    sleep 10
done

killme_0 killme_1 killme_2 killme_3 killme_4 killme_5 killme_6 killme_7 killme_8 killme_9 killme_10
killme_11 killme_12 killme_13 killme_14 killme_15 killme_16 killme_17 killme_18 killme_19 killme_20

docker stats killme_0 killme_1 killme_2 killme_3 killme_4 killme_5 killme_6 killme_7 killme_8 killme_9 killme_10