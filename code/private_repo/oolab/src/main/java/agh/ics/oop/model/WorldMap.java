package agh.ics.oop.model;

import java.util.UUID;


public interface WorldMap extends MoveValidator, AnimalMovedListener {
    /**
     * Return a map identifier.
     *
     * @return UUID of the map.
     */
    UUID getId();

    /**
     * Return the height of the map.
     *
     * @return Height of the map.
     */
    int getWidth();

    /**
     * Return the height of the map.
     *
     * @return Height of the map.
     */
    int getHeight();

    /**
     * Return an animal at a given position.
     *
     * @param position The position of the animal.
     * @return animal or null if the position is not occupied.
     */
    WorldElement objectAt(Vector2d position);

    /**
     * Return true if given position on the map is occupied. Should not be
     * confused with canMove since there might be empty positions where the animal
     * cannot move.
     *
     * @param position Position to check.
     * @return True if the position is occupied.
     */
    boolean isOccupied(Vector2d position);
}