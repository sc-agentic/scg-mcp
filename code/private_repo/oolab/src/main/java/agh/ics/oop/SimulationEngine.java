package agh.ics.oop;

import java.util.concurrent.*;
import java.util.ArrayList;
import java.util.List;
import java.util.HashMap;
import java.util.Map;

public class SimulationEngine {
    private static SimulationEngine instance;
    private final ExecutorService executorService;
    private final BlockingQueue<Simulation> simulations = new LinkedBlockingQueue<>();
    private final Map<Simulation, Thread> runningSimulations = new HashMap<>();

    private SimulationEngine() {
        this.executorService = Executors.newCachedThreadPool();
    }

    public static synchronized SimulationEngine getInstance() {
        if (instance == null) {
            instance = new SimulationEngine();
        }
        return instance;
    }

    public void addSimulation(Simulation simulation) {
        try {
            simulations.put(simulation);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    public void runAsyncInThreadPool() {
        executorService.submit(() -> {
            try {
                while (!Thread.currentThread().isInterrupted()) {
                    Simulation simulation = simulations.take();
                    Thread simulationThread = new Thread(simulation);
                    synchronized (runningSimulations) {
                        runningSimulations.put(simulation, simulationThread);
                    }
                    simulationThread.start();
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        });
    }

    public void stopSimulation(Simulation simulation) {
        synchronized (runningSimulations) {
            Thread thread = runningSimulations.get(simulation);
            if (thread != null) {
                thread.interrupt();
                runningSimulations.remove(simulation);
            }
        }
    }

    public void stopAllSimulations() {
        synchronized (runningSimulations) {
            for (Map.Entry<Simulation, Thread> entry : runningSimulations.entrySet()) {
                Simulation simulation = entry.getKey();
                Thread thread = entry.getValue();
                thread.interrupt();
            }
            runningSimulations.clear();
        }
    }

    public void shutdown() {
        stopAllSimulations();
        executorService.shutdownNow();
    }
}
