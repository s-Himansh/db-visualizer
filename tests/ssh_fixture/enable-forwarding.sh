#!/bin/sh
# linuxserver/openssh-server forbids port forwarding by default; the tunnel tests need it.
sed -i 's/^AllowTcpForwarding no/AllowTcpForwarding yes/' /config/sshd/sshd_config
# OpenSSH 9.8+ temporarily refuses connections from an address after failed logins. The tests fail logins on
# purpose (wrong password, wrong key), so switch that protection off for this throwaway server only.
grep -q '^PerSourcePenalties' /config/sshd/sshd_config || echo 'PerSourcePenalties no' >> /config/sshd/sshd_config
