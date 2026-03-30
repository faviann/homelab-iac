How did I choose which server to connect to for gluetun?

a)First checked which servers I wanted to connect to (the 10gbit) using this:
	https://windscribe.com/status/
  Found that Montreal - Expo 67 had a 10gbit (yeah)

b) I then generated a wireguard file from here: https://windscribe.com/getconfig/wireguard
   this allowed me to find the hostname to look for (yul-359-wg.windscribe.com)

c) I then opened the servers.json from gluetun and looked for all yul-359 instances and registered their hostname.It game me:
- ca-050.whiskergalaxy.com
- ca-051.whiskergalaxy.com
- ca-052.whiskergalaxy.com
- ca-053.whiskergalaxy.com

For the NEW YORKS
-us-east-116.whiskergalaxy.com
- us-east-120.whiskergalaxy.com

d) finally added the 4 hostnames to the docker compose of the stack