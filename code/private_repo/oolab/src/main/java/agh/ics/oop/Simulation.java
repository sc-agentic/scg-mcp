package agh.ics.oop;

import agh.ics.oop.model.*;

public class Simulation implements Runnable {
    private final Globe map;
    private boolean paused = false;

    public Simulation(Globe map) {
        this.map = map;
    }

    public synchronized void pause() {
        System.out.println("Paused");
        paused = true;
    }

    public synchronized void resume() {
        System.out.println("Resumed");
        paused = false;
        notifyAll();
    }

    public synchronized void checkPaused() throws InterruptedException {
        while (paused) {
            wait();
        }
    }

    @Override
    public void run() {
        map.initialSpawn();

        try {
            while (!Thread.currentThread().isInterrupted()) {
                map.nextDay();
                Thread.sleep(500);
                checkPaused();
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}