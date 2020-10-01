#!/usr/bin/env python3

from __future__ import division, absolute_import, print_function, unicode_literals

import subprocess
import re
import time
import argparse
import yaml
from timeparse import timeparse


def call(args):
    return '\n'.join(subprocess.check_output(args).decode().splitlines())


def get_all_statuses():
    return [tuple(x.split(",")) for x in call(["docker", "ps", "--all", "--format", "{{.ID}},{{.Status}}"]).splitlines()]


def get_statuses_for_ids(ids):
    status_list = get_all_statuses()
    statuses = {}
    for id in ids:
        status = None
        for s in status_list:
            if id.find(s[0]) == 0:
                status = s[1]
                break
        if status is None:
            status = "removed"
        statuses[id] = status
    return statuses


def convert_status(s):
    res = re.search(r"^([^\s]+)[^\(]*(?:\((.*)\).*)?$", s)
    if res is None:
        raise Exception("Unknown status format %s" % s)
    if res.group(1) == "Up":
        if res.group(2) == "health: starting":
            return "starting"
        elif res.group(2) == "healthy":
            return "healthy"
        elif res.group(2) == "unhealthy":
            return "unhealthy"
        elif res.group(2) is None:
            return "up"
        else:
            raise Exception("Unknown status format %s" % s)
    else:
        return "down"


def get_converted_statuses(ids):
    return dict([(k, convert_status(v)) for k, v in get_statuses_for_ids(ids).items()])


def get_docker_compose_args(args):
    nargs = []
    for f in args.file:
        nargs += ['-f', f]
    if args.project_name:
        nargs += ['-p', args.project_name]
    return nargs


def get_services_ids(dc_args):
    services_names = yaml.safe_load(call(["docker-compose"] + dc_args + ["config"]))["services"].keys()
    services = {}
    for name in services_names:
        id = call(["docker-compose"] + dc_args + ["ps", '-q', name]).strip()
        if id == '':
            continue
        services[name] = id
    return services


def get_services_statuses(services_with_ids, exception_list):
    statuses_by_id = get_converted_statuses(services_with_ids.values())
    return dict([(k, statuses_by_id[v]) for k, v in services_with_ids.items() if k not in exception_list])


def main():
    parser = argparse.ArgumentParser(
        description='Wait until all services in a docker-compose file are healthy. Options are forwarded to docker-compose.',
        usage='docker-compose-wait.py [options]'
        )
    parser.add_argument('-f', '--file', action='append', default=[],
                        help='Specify an alternate compose file (default: docker-compose.yml)')
    parser.add_argument('-p', '--project-name',
                        help='Specify an alternate project name (default: directory name)')
    parser.add_argument('-w', '--wait', action='store_true',
                        help='Wait for all the processes to stabilize before exit (default behavior is to exit '
                        + 'as soon as any of the processes is unhealthy)')
    parser.add_argument('-t', '--timeout', default=None,
                        help='Max amount of time during which this command will run (expressed using the '
                        + 'same format than in docker-compose.yml files, example: 5s, 10m,... ). If there is a '
                        + 'timeout this command will exit returning 1. (default: wait for an infinite amount of time)')
    parser.add_argument('-b', '--blacklist', type=str, default=None,
                        help='Comma-delimited list of services to exclude from wait. i.e. services that could be'
                        + 'unhealthy.'
                        )

    args = parser.parse_args()
    dc_args = get_docker_compose_args(args)

    start_time = time.time()
    timeout = timeparse(args.timeout) if args.timeout is not None else None

    services_ids = get_services_ids(dc_args)

    up_statuses = set(['healthy', 'up'])
    down_statuses = set(['down', 'unhealthy', 'removed', 'Exit'])
    stabilized_statuses = up_statuses | down_statuses
    blacklist = [str(bl.strip()) for bl in args.blacklist.split(',')] if args.blacklist else []

    while True:
        statuses = get_services_statuses(services_ids, blacklist)

        if args.wait:
            if any([v not in stabilized_statuses for k, v in statuses.items()]):
                continue

        if all([v in up_statuses for k, v in statuses.items()]):
            msg = "All processes up and running in {} sec".format(int(time.time() - start_time))
            if blacklist:
                msg = msg+('\nDid not wait for: {}'.format(blacklist))
            print(msg)
            exit(0)
        elif any([v in down_statuses for k, v in statuses.items()]):
            print("Some processes failed:")
            for k, v in [(k, v) for k, v in statuses.items() if v in down_statuses]:
                print("%s is %s" % (k, v))
            exit(-1)

        if args.timeout is not None and time.time() > start_time + timeout:
            print("Timeout")
            exit(1)

        time.sleep(1)


if __name__ == "__main__":
    # execute only if run as a script
    main()
