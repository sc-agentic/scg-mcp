package agh.ics.oop.model;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

public class Vector2d {
    final private int x;
    final private int y;

    public Vector2d(int x, int y) {
        this.x = x;
        this.y = y;
    }

    public int getX() {
        return x;
    }

    public int getY() {
        return y;
    }

    @Override
    public String toString() {
        return "(%s,%s)".formatted(getX(), getY());
    }



    public Vector2d add(Vector2d other) {
        return new Vector2d(x + other.x, y + other.y);
    }

    public boolean equals(Object other) {
        if (this == other) return true;
        if (!(other instanceof Vector2d that)) return false;

        return getX() == that.getX() && getY() == that.getY();
    }

    @Override
    public int hashCode() {
        return Objects.hash(getX(), getY());
    }

    public List<Vector2d> getSurroundingPositions() {
        ArrayList<Vector2d> positions = new ArrayList<>();
        for (int i = x - 1; i <= x + 1; i++) {
            for (int j = y - 1; j <= y + 1; j++) {
                positions.add(new Vector2d(i, j));
            }
        }
        return positions;
    }
}
