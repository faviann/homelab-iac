# Use persistent policy for destructive lifecycle plans

A destructive LXC lifecycle plan executes in the same full lifecycle run when persistent inventory policy explicitly authorizes its transition; no interactive or per-run confirmation is added. Destructive behavior remains disabled by default, and the lifecycle planning barrier must still produce valid plans for every targeted LXC before any authorized action begins.
