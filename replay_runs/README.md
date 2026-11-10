# Replay runs

Saved runs of the d=3 surface-code memory experiment, ready to play on the screen
and the LED panel: `python Run_Circuit.py`, Mode **Replay**, **Choose folder...**, then
pick one of the `<category>_shot<N>` folders below.

```
replay_runs/
  simulations/   made by IBM_Run.py on the ideal simulator and on noisy fake IBM devices
  IBM_runs/      the same experiment on real IBM hardware (IBM_Run.py --hardware)
    <date>_<backend>_r<rounds>/
      summary.json                 every case: logical error rate, detection rates, circuit size
      job.json                     (hardware only) job id, to fetch results later with --retrieve
      <case>/
        case.json                  planned faults, numbers, which shots were saved
        shots.json                 raw bits of every shot (re-decode without re-running)
        clean_shot00012/           no detection events
        corrected_shot00003/       detection events, decoded correctly
        logical_failure_shot00007/ decoded to the wrong logical value
          frame_0000.json ...      LED frames (Data_Log/Pico_Frames.py format)
          steps.json               which step each frame shows
```

## The experiment (Simulation_Logic/hardware.py)

One circuit per case, nothing paused or applied mid-run, so it runs unchanged on hardware:

1. data qubits start in |0> (every Z check +1; the first X-check round projects onto |0_L>)
2. N rounds (default 3) of X checks then Z checks, with mid-circuit measurement and reset
3. all 9 data qubits measured in Z: gives a last, perfect set of Z checks and Z_L = D1 D2 D3

Decoding is space-time MWPM afterwards. Detection events compare each round with the one
before, so **a data error flags its checks once, a measurement error flags the same check
twice in a row**. The frames show the data errors the decoder infers (hardware gives no
direct view of them) and the logical verdict appears on the last frame.

Each shot folder has 3 frames per round (X checks, Z checks, decode), then the final
readout and the final verdict, after an opening reset frame.

## Built-in cases (faults in round 2 by default)

| case | planned fault | ideal result |
|---|---|---|
| `idle` | none | no detection events |
| `x_D5` | X on D5 | Z1, Z2 flag once; corrected |
| `z_D3` | Z on D3 | X0 flags once; corrected |
| `y_D5` | Y on D5 | both kinds; corrected |
| `meas_Z1` | Z1's result flipped in round 2 | Z1 flags in rounds 2 and 3; no data correction |
| `meas_X2` | X2's result flipped in round 2 | X2 flags in rounds 2 and 3 |
| `x_D1_D4` | X on D1 and D4 | MWPM adds X on D7: logical failure every time |
| `x_D9_late` | X on D9 just before readout | only the readout's Z checks see it; corrected |

Your own: `python IBM_Run.py --case "name=X:D5@2,M:Z1@3"` (data error `X|Y|Z:D1..D9@round`,
round = rounds + 1 means just before the readout; measurement error `M:X0..Z3@round`).

## On noisy devices

Heavy-hex chips connect each qubit to at most 3 others, but a weight-4 check needs its
ancilla to talk to 4 data qubits, so the transpiler adds SWAPs: about 260-290 two-qubit
gates per circuit instead of 72. Expect frequent detection events and a logical error
rate of tens of percent; a single planned fault uses up the code's one correctable error,
so any extra device error on top of it can cause a logical failure.
