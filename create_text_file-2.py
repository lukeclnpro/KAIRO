import os

def create_text_file(filename, content):
    if not filename.endswith('.txt'):
        print("Le nom du fichier doit se terminer par .txt")
        return
    if not content:
        print("Le contenu ne peut pas être vide")
        return
    try:
        with open(filename, 'w') as file:
            file.write(content)
        print(f"Fichier '{filename}' créé avec succès.")
    except Exception as e:
        print(f"Une erreur est survenue : {e}")

if __name__ == '__main__':
    nom_fichier = input("Entrez le nom du fichier (avec .txt) : ")
    contenu = input("Entrez le contenu du fichier : ")
    create_text_file(nom_fichier, contenu)