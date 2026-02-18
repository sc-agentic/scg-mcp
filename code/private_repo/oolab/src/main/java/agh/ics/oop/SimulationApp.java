package agh.ics.oop;


import javafx.application.Application;
import javafx.application.Platform;
import javafx.fxml.FXMLLoader;
import javafx.scene.Scene;
import javafx.scene.layout.BorderPane;
import javafx.stage.Stage;

import java.io.IOException;

public class SimulationApp extends Application {
  public void start(Stage primaryStage) {
    FXMLLoader loader = new FXMLLoader();
    loader.setLocation(getClass().getClassLoader().getResource("simulation.fxml"));
    BorderPane viewRoot = null;
    try {
        viewRoot = loader.load();
    } catch (IOException e) {
        e.printStackTrace();
    }
    configureStage(primaryStage, viewRoot);
  }

  private void configureStage(Stage primaryStage, BorderPane viewRoot) {
    var scene = new Scene(viewRoot);

    primaryStage.setOnCloseRequest(event -> {
        SimulationEngine.getInstance().shutdown();
        Platform.exit();
    });

    primaryStage.setScene(scene);
    primaryStage.setTitle("Simulation");
    primaryStage.minWidthProperty().bind(viewRoot.minWidthProperty());
    primaryStage.minHeightProperty().bind(viewRoot.minHeightProperty());
    primaryStage.show();
  }
}
