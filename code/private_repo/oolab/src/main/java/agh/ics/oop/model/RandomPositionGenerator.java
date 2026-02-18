package agh.ics.oop.model;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.Random;

public class RandomPositionGenerator implements Iterable<Vector2d> {
    private final ArrayList<Vector2d> initialAvailablePositions;
    private final int positionCount;

    public RandomPositionGenerator(ArrayList<Vector2d> availablePositions, int positionCount) {
        if (availablePositions.size() < positionCount) {
            throw new IllegalArgumentException("Position count exceeds the number of available positions.");
        }

        this.initialAvailablePositions = availablePositions;
        this.positionCount = positionCount;
    }

    @Override
    public Iterator<Vector2d> iterator() {
        return new Iterator<>() {
            private int generatedCount;
            private final Random random = new Random();
            private final ArrayList<Vector2d> availablePositions = initialAvailablePositions;

            @Override
            public boolean hasNext() {
                return generatedCount < positionCount;
            }

            @Override
            public Vector2d next() {
                if (!hasNext()) {
                    throw new IllegalStateException("Already generated all elements");
                }

                Vector2d chosenPosition = availablePositions.remove(random.nextInt(availablePositions.size()));
                generatedCount++;
                return chosenPosition;
            }
        };
    }
}
