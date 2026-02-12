package agh.ics.oop.model;

import java.util.ArrayList;
import java.util.Objects;

public class Genotype {
  private final ArrayList<Integer> genes;
  private int lastUsedGeneIndex;

  /*
   * This constructor should create a new gene by combining genes from parent1 and parent2.
   * The split is a number between 0 and 1, which determines how much genes comes from parent1.
   */
  public Genotype(Animal parent1, Animal parent2) {
    if (parent1.getGenotype().getGenes().size() != parent2.getGenotype().getGenes().size()) {
      throw new IllegalArgumentException("Genotypes sizes are not equal");
    }

    int genotypeSize = parent1.getGenotype().getGenes().size();

    float split = (float) parent1.getEnergy() / (parent1.getEnergy() + parent2.getEnergy());
    int splitIndex;
    if (Math.random() < 0.5) {
      splitIndex = (int) split * genotypeSize;
    } else {
      splitIndex = (int) (1 - split) * genotypeSize;
    }

    genes = new ArrayList<>();
    genes.addAll(parent1.getGenotype().getGenes().subList(0, splitIndex));
    genes.addAll(parent2.getGenotype().getGenes().subList(splitIndex, genotypeSize));

    mutate();
    setRandomStartGene();
  }

  public Genotype(int genotypeSize) {
    genes = new ArrayList<>();
    for (int i = 0; i < genotypeSize; i++) {
      int randomGene = (int) (Math.random() * 7);
      genes.add(randomGene);
    }
    setRandomStartGene();
  }


  public ArrayList<Integer> getGenes() {
    return genes;
  }

  public int getLastUsedGeneIndex() {
    return lastUsedGeneIndex;
  }

  @Override
  public int hashCode() {
    return Objects.hash(genes);
  }

  private void setRandomStartGene() {
    lastUsedGeneIndex = (int) (Math.random() * genes.size());
  }

  public int getNextGene() {
    lastUsedGeneIndex = (lastUsedGeneIndex + 1) % genes.size();
    return genes.get(lastUsedGeneIndex);
  }

  void mutate() {
    int valuesToMutate = (int) (Math.random() * genes.size());

    for (int i = 0; i < valuesToMutate; i++) {
      int randomIndex = (int) (Math.random() * genes.size());  // gene can be mutated multiple times
      int randomValue = (int) (Math.random() * 7);
      genes.set(randomIndex, randomValue);
    }
  }
  @Override
  public String toString(){
    return genes.toString();
  }
}
