# Copyright (c) 2015 Canonical Ltd
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Manage edits to lxc-usernet(5) style file (/etc/lxc/lxc-usernet).
File is
  * comment lines (#)
  * <username> <type> <bridge> <count>

example:
  # USERNAME TYPE BRIDGE COUNT
  ubuntu veth br100 128
"""

import os
import argparse
import tempfile

from oslo_concurrency import lockutils

ETC_LXC_USERNET = "/etc/lxc/lxc-usernet"


class UserNetLine(object):

    def __init__(self, line):
        self.error = None
        line = line.rstrip("\n")
        cpos = line.find("#")
        user = None
        ntype = None
        brname = None
        count = None
        if cpos < 0:
            payload = line.strip()
            comment = None
        else:
            payload = line[:cpos].strip()
            comment = line[cpos:]

        if payload:
            try:
                user, ntype, brname, count = payload.split()
            except ValueError:
                # don't understand this line.
                self.error = line
        else:
            comment = line

        self.user = user
        self.bridge = brname
        self.ntype = ntype
        self.count = count
        self.comment = comment

    def __repr__(self):
        return(self.__str__())

    def __str__(self):
        if self.error is not None:
            return self.error

        if self.user:
            comm = ""
            if self.comment:
                comm = " " + self.comment
            return ("%s %s %s %s" % (self.user, self.ntype, self.bridge,
                                     str(self.count) + comm))
        return self.comment


def load_usernet(fname):
    lines = []
    with open(fname, "r") as fp:
        for line in fp:
            lines.append(UserNetLine(line))
    return lines


def write_usernet(fname, lines, drop=None):
    if drop:
        nlines = []
        for i, l in enumerate(lines):
            if i not in drop:
                nlines.append(l)
        lines = nlines
    tf = None
    try:
        tf = tempfile.NamedTemporaryFile(dir=os.path.dirname(fname),
                                         delete=False)
        for l in lines:
            tf.write(str(l) + "\n")
        tf.close()

        if os.path.isfile(fname):
            statl = os.stat(fname)
            os.chmod(tf.name, statl.st_mode)
            os.chown(tf.name, statl.st_uid, statl.st_gid)
        else:
            os.chmod(tf.name, 0o644)

        os.rename(tf.name, fname)
    finally:
        if tf is not None and os.path.isfile(tf.name):
            os.unlink(tf.name)


def update_usernet(user, bridge, op, count=1, ntype="veth",
                   strict=False, fname=ETC_LXC_USERNET):

    ops = ("set", "inc", "dec")
    if op not in ops:
        raise TypeError("op = '%s'. must be one of %s",
                        (op, ','.join(ops)))

    minfo = "user=%s, bridge=%s, ntype=%s" % (user, bridge, ntype)
    lines = load_usernet(fname)

    found = []
    for i, l in enumerate(lines):
        if (user != l.user or bridge != l.bridge or l.ntype != ntype):
            continue
        found.append(i)

    if strict and not found and op != "set":
        raise ValueError("EntryNotFound: %s" % minfo)

    if not found:
        if op == "dec":
            # decrement non-existing, assume zero
            return
        newline = UserNetLine("")
        newline.user = user
        newline.ntype = ntype
        newline.bridge = bridge
        newline.count = int(count)
        lines.append(newline)
    else:
        # update the last one (others deleted on write)
        line = lines[found[-1]]
        if op == "inc":
            line.count = int(line.count) + int(count)
        elif op == "dec":
            line.count = int(line.count) - int(count)
        elif op == "set":
            if len(found) == 1 and line.count == count and count != 0:
                return
            line.count = count
        if line.count == 0:
            # set or dec to '0'. add this line to found, for delete
            found.append(found[-1])

    write_usernet(fname, lines, found[:-1])


def lfilter(fname, user=None, bridge=None, count=None, ntype="veth"):
    ret = []
    for f in load_usernet(fname):
        if user is not None and f.user != user:
            continue
        if bridge is not None and f.bridge != bridge:
            continue
        if count is not None and str(f.count) != str(count):
            continue
        if ntype is not None and f.ntype != ntype:
            continue
        ret.append(f)
    return ret


def manage_main():
    fname = ETC_LXC_USERNET

    parser = argparse.ArgumentParser()
    parser.add_argument("--type", "-t", help="nic type (default: 'veth')",
                        default="veth", dest="ntype")
    parser.add_argument(
        'operation',
        choices=(
            "set",
            "inc",
            "dec",
            "del",
            "get"))
    parser.add_argument('user', help="username")
    parser.add_argument('bridge', help="bridge")
    parser.add_argument('count', nargs="?", help="number to operate with.",
                        default=None, const=int)

    args = parser.parse_args()
    if args.operation == "del":
        args.operation = "set"
        args.count = 0
    elif args.operation in ("set", "inc", "dec") and args.count is None:
        args.count = 1

    if args.operation == "get":
        if args.bridge == "*":
            args.bridge = None
        matching = lfilter(fname, user=args.user, bridge=args.bridge,
                           count=args.count, ntype=args.ntype)
        for l in matching:
            print(str(l))
        return 0

    with lockutils.lock(str(fname)):
        update_usernet(user=args.user, bridge=args.bridge, op=args.operation,
                       count=args.count, ntype=args.ntype, fname=fname)
