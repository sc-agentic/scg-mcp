package agh.ics.oop.model;

public interface AnimalMovedListener {
    void animalMoved(Vector2d oldPosition, Vector2d newPosition, Animal animal);
}
