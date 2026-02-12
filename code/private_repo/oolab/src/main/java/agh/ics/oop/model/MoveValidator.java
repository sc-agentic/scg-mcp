package agh.ics.oop.model;

public interface MoveValidator {

    /*
     * @param initialPosition
     *            The initial position of the object.
     * @param targetPosition
     *            The target position of the object.
     * @return Position to which an object should be moved.
     */
    Vector2d validateMove(Vector2d initialPosition, Vector2d targetPosition);

    /*
     * @param position
     *            The position checked for the movement possibility.
     * @param direction
     *            The direction of the movement.
     * @return Direction to which on object should be directed.
     */
    MapDirection validateDirection(Vector2d position, MapDirection direction);
}
