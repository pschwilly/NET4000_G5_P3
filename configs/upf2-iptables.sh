#!/bin/sh
iptables -I FORWARD 1 -j ACCEPT
iptables -t nat -A POSTROUTING -s 10.61.0.0/16 -o eth1 -j MASQUERADE
